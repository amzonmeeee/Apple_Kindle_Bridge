"""Both libraries, the saved book pairs, and what can be transferred.

Pairs are stored when the app uploads a book or when an exact title match is
unique on both sides. Content verification happens when a position or highlight
is first mapped; a failure there is reported on the pair, never guessed around.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unicodedata

from . import paths
from .apple import discover, file_status, snapshot

# Observed: a 158 MB EPUB was refused; the documented e-mail limit is 50 MB.
SEND_LIMIT = 50 * 1024 * 1024
PROTECTED_MARKERS = ('META-INF/sinf.xml', 'META-INF/encryption.xml', 'META-INF/rights.xml')


def norm_title(title):
    text = unicodedata.normalize('NFKC', title or '').casefold()
    text = re.sub(r'[《》「」『』“”"\'’‘:：\-—_.,，。!！?？()（）\[\]【】\s]+', '', text)
    return text


def pairs_file():
    return paths.data_dir() / 'pairs.json'


def load_pairs():
    path = pairs_file()
    return json.loads(path.read_text()) if path.exists() else []


def save_pairs(pairs):
    path = pairs_file()
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(pairs, ensure_ascii=False, indent=2))
    temp.replace(path)


def add_pair(apple_id, kindle_id, method):
    pairs = [p for p in load_pairs() if p['apple_asset_id'] != apple_id and p['kindle_book_id'] != kindle_id]
    pairs.append({'apple_asset_id': apple_id, 'kindle_book_id': kindle_id, 'method': method,
                  'created': datetime.now(timezone.utc).isoformat()})
    save_pairs(pairs)


def remove_pair(apple_id):
    save_pairs([p for p in load_pairs() if p['apple_asset_id'] != apple_id])


def protected_epub(path):
    path = Path(path)
    if path.is_dir():
        return any((path / marker).exists() for marker in PROTECTED_MARKERS)
    import zipfile
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return True
    return any(marker in names for marker in PROTECTED_MARKERS)


def apple_books():
    library, annotations = discover()
    with snapshot(library) as db:
        rows = [dict(r) for r in db.execute(
            'SELECT ZASSETID,ZTITLE,ZAUTHOR,ZPATH,ZSTOREID FROM ZBKLIBRARYASSET '
            'WHERE ZTITLE IS NOT NULL AND ZASSETID IS NOT NULL')]
    books = []
    for row in rows:
        info = file_status(row['ZPATH'])
        path = info.get('path')
        entry = {'id': row['ZASSETID'], 'title': row['ZTITLE'], 'author': row['ZAUTHOR'] or '',
                 'path': path, 'store': bool(row['ZSTOREID'])}
        suffix = Path(str(path)).suffix.lower() if path else ''
        if not path:
            # Store books that are not downloaded have no file; they carry DRM anyway.
            entry['kind'], entry['reason'] = ('protected', 'Apple Books Store purchase with DRM') if row['ZSTOREID'] \
                else ('not_downloaded', 'Download it in Apple Books first')
        elif suffix == '.pdf' and info['status'] == 'file':
            entry['size'] = Path(path).stat().st_size
            # PDFs can be sent to Kindle, but positions and highlights do not map.
            entry['kind'], entry['reason'] = ('send_only', 'PDF') if entry['size'] <= SEND_LIMIT \
                else ('too_large', 'Over the 50 MB Send to Kindle limit')
        elif suffix != '.epub':
            entry['kind'], entry['reason'] = 'unsupported', 'Not an EPUB or PDF'
        elif info['status'] == 'missing':
            entry['kind'], entry['reason'] = 'not_downloaded', 'Download it in Apple Books first'
        elif row['ZSTOREID'] or protected_epub(path):
            entry['kind'], entry['reason'] = 'protected', 'Apple Books Store purchase with DRM'
        else:
            entry['kind'] = 'transferable'
        books.append(entry)
    return books


def kindle_books(modules):
    books = []
    for book in modules['ksdk'].load_kindle_books():
        entry = {'id': book.bookid, 'title': book.title, 'type': book.content_type,
                 'downloaded': bool(book.guid) and bool(book.maxpos), 'format': 'kfx' if book.is_kfx else 'other'}
        if book.content_type == 'EBOK':
            entry['kind'], entry['reason'] = 'protected', 'Kindle Store purchase with DRM'
        elif not entry['downloaded']:
            entry['kind'], entry['reason'] = 'not_downloaded', 'Download it in Kindle for Mac first'
        elif not book.is_kfx:
            entry['kind'], entry['reason'] = 'unsupported', 'Only KFX books are supported'
        else:
            entry['kind'] = 'transferable'
        books.append(entry)
    return books


def overview(modules):
    apple, kindle = apple_books(), kindle_books(modules)
    apple_by_id = {b['id']: b for b in apple}
    kindle_by_id = {b['id']: b for b in kindle}
    pairs = [p for p in load_pairs() if p['apple_asset_id'] in apple_by_id and p['kindle_book_id'] in kindle_by_id]
    paired_apple = {p['apple_asset_id'] for p in pairs}
    paired_kindle = {p['kindle_book_id'] for p in pairs}
    # Exact unique titles on both sides become pairs automatically.
    def index(books, used):
        found = {}
        for b in books:
            if b['id'] not in used and b['kind'] in ('transferable', 'not_downloaded') \
                    and not str(b.get('path') or '').lower().endswith('.pdf'):
                found.setdefault(norm_title(b['title']), []).append(b)
        return found
    apple_titles = index(apple, paired_apple)
    kindle_titles = index([b for b in kindle if b['type'] == 'PDOC'], paired_kindle)
    for key, candidates in apple_titles.items():
        match = kindle_titles.get(key)
        if key and len(candidates) == 1 and match and len(match) == 1:
            add_pair(candidates[0]['id'], match[0]['id'], 'title')
            pairs.append({'apple_asset_id': candidates[0]['id'], 'kindle_book_id': match[0]['id'], 'method': 'title'})
            paired_apple.add(candidates[0]['id'])
            paired_kindle.add(match[0]['id'])
    result = {'pairs': [], 'apple_only': [], 'kindle_only': [], 'protected': []}
    for p in pairs:
        a, k = apple_by_id[p['apple_asset_id']], kindle_by_id[p['kindle_book_id']]
        ready = a['kind'] == 'transferable' and k['kind'] == 'transferable'
        result['pairs'].append({'apple': a, 'kindle': k, 'method': p.get('method'), 'ready': ready,
                                'reason': None if ready else (a.get('reason') if a['kind'] != 'transferable' else k.get('reason'))})
    for b in apple:
        if b['id'] not in paired_apple:
            (result['protected'] if b['kind'] == 'protected' else result['apple_only']).append(b)
    for b in kindle:
        if b['id'] not in paired_kindle:
            (result['protected'] if b['kind'] == 'protected' else result['kindle_only']).append({**b, 'side': 'kindle'})
    return result
