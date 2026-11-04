"""Page-level reading positions for PDFs sent to Kindle.

Apple Books stores a PDF position as a page index (BKPageLocation.pageOffset).
Send to Kindle converts the PDF to a KFX book whose text keeps the page order.
Pages are matched by their text, ignoring spaces and punctuation, which PDF
text extraction and the conversion handle differently.
"""
import bisect
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import subprocess
import tempfile
import time

from . import paths
from .apple import snapshot

SNIPPET = 24


def compact(text):
    """Letters and digits only, lower case, with the source index of each kept character."""
    kept, index = [], []
    for i, ch in enumerate(text):
        if ch.isalnum():
            kept.append(ch.lower())
            index.append(i)
    return ''.join(kept), index


def page_texts(pdf):
    """Text of each page, cached by file content."""
    pdf = Path(pdf)
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    cache = paths.data_dir() / 'pdf-cache'
    cache.mkdir(exist_ok=True)
    cached = cache / f'{digest}.json'
    if cached.exists():
        return json.loads(cached.read_text())
    resources = os.environ.get('AKB_RESOURCES')
    tool = Path(resources) / 'pdftext' if resources else paths.ROOT / '.runtime' / 'pdftext'
    run = subprocess.run([str(tool), str(pdf)], capture_output=True, timeout=120)
    if run.returncode:
        raise ValueError('Could not read the PDF text')
    pages = json.loads(run.stdout)
    cached.write_text(json.dumps(pages, ensure_ascii=False))
    return pages


class PdfMap:
    def __init__(self, pages, reader):
        self.pages = [compact(p)[0] for p in pages]
        self.starts, offset = [], 0
        for text in self.pages:
            self.starts.append(offset)
            offset += len(text)
        self.pdf_text = ''.join(self.pages)
        self.reader = reader
        self.kindle_text, kindle_index = compact(reader.stripped)
        self.kindle_pos = [reader.pos[i] for i in kindle_index]

    def page_to_kindle(self, page):
        """Kindle position of the first text on a page, or of the nearest page with text."""
        for candidate in list(range(page, len(self.pages))) + list(range(page - 1, -1, -1)):
            text = self.pages[candidate]
            for skip in range(0, max(1, len(text) - SNIPPET), 4):
                snippet = text[skip:skip + SNIPPET]
                if len(snippet) == SNIPPET and self.kindle_text.count(snippet) == 1:
                    # Stay on the matched text. Stepping back by `skip` can land on
                    # the previous page, since page numbers sit in different places.
                    return self.kindle_pos[self.kindle_text.index(snippet)], candidate
        raise ValueError('No page text could be found in the Kindle book')

    def kindle_to_page(self, position):
        """Page holding the text at a Kindle position."""
        index = bisect.bisect_left(self.kindle_pos, position)
        for skip in range(0, 4000, 4):
            snippet = self.kindle_text[index + skip:index + skip + SNIPPET]
            if len(snippet) < SNIPPET:
                break
            if self.pdf_text.count(snippet) == 1:
                at = self.pdf_text.index(snippet)
                page = bisect.bisect_right(self.starts, at) - 1
                # Text further on can sit on the next page; step back when the
                # skipped text began on an earlier page.
                while page > 0 and at - skip < self.starts[page]:
                    page -= 1
                return page
        raise ValueError('The Kindle position could not be placed on a PDF page')


def apple_page(db, asset_id):
    rows = db.execute('SELECT Z_PK,Z_OPT,ZPLUSERDATA,ZANNOTATIONMODIFICATIONDATE FROM ZAEANNOTATION '
                      'WHERE ZANNOTATIONASSETID=? AND ZANNOTATIONTYPE=3 AND ZANNOTATIONDELETED=0',
                      (asset_id,)).fetchall()
    if len(rows) != 1 or rows[0][2] is None:
        raise ValueError('Open the PDF once in Apple Books first')
    data = plistlib.loads(rows[0][2])
    if data.get('class') != 'BKPageLocation':
        raise ValueError('Unexpected Apple Books PDF position')
    return {'Z_PK': rows[0][0], 'Z_OPT': rows[0][1], 'page': data['pageOffset'],
            'updated': (rows[0][3] or 0) + 978307200, 'raw': rows[0][2]}


def write_apple_page(annotations, asset_id, expected, page, total):
    data = plistlib.loads(expected['raw'])
    data['pageOffset'] = page
    blob = plistlib.dumps(data, fmt=plistlib.FMT_BINARY)
    fraction = str(round((page + 1) / total, 9)) if total else None
    with sqlite3.connect(annotations) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT Z_OPT,ZPLUSERDATA FROM ZAEANNOTATION WHERE Z_PK=?', (expected['Z_PK'],)).fetchone()
        if row is None or row[0] != expected['Z_OPT'] or row[1] != expected['raw']:
            raise ValueError('Apple Books position changed; check again before syncing')
        # The same modification stamps as the verified EPUB writer. iCloud sync
        # reads ZFUTUREPROOFING6 and 11, not only the modification date.
        modified = time.time() - 978307200
        db.execute('UPDATE ZAEANNOTATION SET ZPLUSERDATA=?, ZFUTUREPROOFING10=COALESCE(?,ZFUTUREPROOFING10), '
                   'ZANNOTATIONMODIFICATIONDATE=?, ZFUTUREPROOFING6=?, ZFUTUREPROOFING11=?, Z_OPT=Z_OPT+1 '
                   'WHERE Z_PK=?', (blob, fraction, modified, str(modified), str(modified), expected['Z_PK']))


CORE_DATA_EPOCH = 978307200
TOLERANCE_PAGES = 0


def open_pair(modules, apple_id, kindle_id):
    from .apple_position import selected_book
    books = [b for b in modules['ksdk'].load_kindle_books() if b.bookid == kindle_id and b.guid]
    if len(books) != 1:
        raise ValueError('Kindle book is not downloaded')
    book = books[0]
    reader = modules['kindle_annots'].open_book(book)
    path, annotations = selected_book(apple_id)
    pdf = PdfMap(page_texts(path), reader)
    kindle_db = Path(modules['ksdk'].LASSEN_DATA) / 'Library/Protected/BookData.sqlite'
    return book, reader, pdf, path, annotations, kindle_db


def kindle_row(kindle_db, kindle_id):
    with snapshot(kindle_db) as db:
        row = db.execute('SELECT Z_PK,Z_OPT,ZBOOKID,ZRAWCURRENTPOSITION,ZLONGCURRENTPOSITION,ZRAWLASTACCESSTIME '
                         'FROM ZBOOK WHERE ZBOOKID=?', ('A:' + kindle_id + '-0',)).fetchone()
    if row is None:
        raise ValueError('Kindle book row is missing')
    return dict(row)


def status(modules, apple_id, kindle_id, baseline):
    book, reader, pdf, path, annotations, kindle_db = open_pair(modules, apple_id, kindle_id)
    with snapshot(annotations) as db:
        apple = apple_page(db, apple_id)
    kindle = kindle_row(kindle_db, kindle_id)
    kindle_pos = kindle['ZRAWCURRENTPOSITION'] or 0
    kindle_page = pdf.kindle_to_page(kindle_pos)
    _, apple_text_page = pdf.page_to_kindle(apple['page'])
    pages = page_texts(path)
    result = {
        'apple': {'page': apple['page'] + 1, 'updated': datetime.fromtimestamp(apple['updated'], timezone.utc).isoformat(),
                  'excerpt': ' '.join(pages[apple['page']].split())[:80] if apple['page'] < len(pages) else ''},
        'kindle': {'position': kindle_pos, 'page': kindle_page + 1,
                   'updated': datetime.fromtimestamp(kindle['ZRAWLASTACCESSTIME'], timezone.utc).isoformat()
                   if kindle['ZRAWLASTACCESSTIME'] else None,
                   'excerpt': reader.extract_text(kindle_pos, kindle_pos + 80).strip(),
                   'percent': round(100 * kindle_pos / book.maxpos, 1) if book.maxpos else None},
        'pdf': True, 'pages': len(pages),
    }
    if abs(kindle_page - apple_text_page) <= TOLERANCE_PAGES:
        result['state'] = 'synced'
        return result
    base = baseline.get('position') or {}
    apple_changed = kindle_changed = True
    if 'apple_page' in base:
        apple_changed = apple['page'] != base['apple_page']
        kindle_changed = kindle_page != base.get('kindle_page')
    if apple_changed and not kindle_changed:
        target = 'kindle'
    elif kindle_changed and not apple_changed:
        target = 'apple'
    else:
        target = 'kindle' if apple['updated'] >= (kindle['ZRAWLASTACCESSTIME'] or 0) else 'apple'
    # Apple Books uploads only changes it records itself, and on a Mac it hands
    # PDFs to Preview, so a written PDF page never reaches iCloud. Only the
    # Apple-to-Kindle direction is offered.
    if target == 'apple':
        result.update(state='kindle_ahead', apple_write_supported=False)
        return result
    result.update(state='conflict' if apple_changed and kindle_changed else 'changed',
                  default_target=target, apple_write_supported=False)
    return result


def quit_app(name, process):
    subprocess.run(['osascript', '-e', f'tell application "{name}" to quit'], capture_output=True)
    for _ in range(120):
        if subprocess.run(['pgrep', '-x', process], capture_output=True).returncode:
            return
        time.sleep(0.5)
    raise ValueError(f'{name} did not close; no writes performed')


def backup(source, prefix):
    folder = paths.backup_dir()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=folder, prefix=prefix, suffix='.sqlite', delete=False) as handle:
        target = Path(handle.name)
    with snapshot(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    return str(target)


def transfer(modules, cfg, apple_id, kindle_id, direction):
    """Move the position to the other app, page by page."""
    book, reader, pdf, path, annotations, kindle_db = open_pair(modules, apple_id, kindle_id)
    if direction == 'apple':
        raise ValueError('Apple Books does not upload a PDF page written by another app; '
                         'only Apple Books to Kindle is supported for PDFs')
    quit_app('Amazon Kindle', 'Kindle')
    with snapshot(annotations) as db:
        apple = apple_page(db, apple_id)
    position, _ = pdf.page_to_kindle(apple['page'])
    kindle = kindle_row(kindle_db, kindle_id)
    saved = backup(kindle_db, 'kindle-')
    with sqlite3.connect(kindle_db) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT Z_OPT FROM ZBOOK WHERE Z_PK=?', (kindle['Z_PK'],)).fetchone()
        if row is None or row[0] != kindle['Z_OPT']:
            raise ValueError('Kindle position changed; check again before syncing')
        db.execute('UPDATE ZBOOK SET ZRAWCURRENTPOSITION=?,ZLONGCURRENTPOSITION=NULL,Z_OPT=Z_OPT+1 WHERE Z_PK=?',
                   (position, kindle['Z_PK']))
    from urllib.parse import urlencode
    subprocess.run(['open', '-g', 'kindle://book?' + urlencode({'action': 'open', 'asin': kindle_id, 'type': 'PDOC'})],
                   capture_output=True)
    return {'status': 'written', 'position': position, 'backup': saved}


def baseline(modules, apple_id, kindle_id):
    book, reader, pdf, path, annotations, kindle_db = open_pair(modules, apple_id, kindle_id)
    with snapshot(annotations) as db:
        apple = apple_page(db, apple_id)
    kindle = kindle_row(kindle_db, kindle_id)
    return {'apple_page': apple['page'], 'kindle_page': pdf.kindle_to_page(kindle['ZRAWCURRENTPOSITION'] or 0)}


# ---- highlights, Apple Books to Kindle only --------------------------------
# Apple Books writes PDF highlights into the PDF file itself, which iCloud
# keeps in step across devices. They are read with PDFKit and placed in the
# Kindle text near their page.

KINDLE_HUES = {'yellow': 50, 'orange': 25, 'pink': 330, 'blue': 210}


def kindle_color(hex_color):
    import colorsys
    if not hex_color or len(hex_color) != 7:
        return 'yellow'
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hue, _, saturation = colorsys.rgb_to_hls(r, g, b)
    if saturation < 0.15:
        return 'yellow'
    degrees = hue * 360
    return min(KINDLE_HUES, key=lambda c: min(abs(degrees - KINDLE_HUES[c]), 360 - abs(degrees - KINDLE_HUES[c])))


def apple_highlights(path):
    resources = os.environ.get('AKB_RESOURCES')
    tool = Path(resources) / 'pdftext' if resources else paths.ROOT / '.runtime' / 'pdftext'
    run = subprocess.run([str(tool), '--annotations', str(path)], capture_output=True, timeout=120)
    if run.returncode:
        raise ValueError('Could not read the PDF highlights')
    found = []
    for item in json.loads(run.stdout):
        if item['type'] not in ('Highlight', 'Underline') or not compact(item.get('text', ''))[0]:
            continue
        text = ' '.join(item['text'].split())
        key = f"{item['page']}:{hashlib.sha1(compact(text)[0].encode()).hexdigest()[:12]}"
        found.append({'key': key, 'page': item['page'], 'text': text,
                      'color': 'yellow' if item['type'] == 'Underline' else kindle_color(item.get('color')),
                      'underline': item['type'] == 'Underline',
                      'note': (item.get('contents') or item.get('popup') or '').strip() or None,
                      'updated': item.get('modified', 0)})
    return found


def locate(pdf, item):
    """Kindle range for a PDF highlight, searched on its page first."""
    needle = compact(item['text'])[0]
    start, _ = pdf.page_to_kindle(item['page'])
    begin = bisect.bisect_left(pdf.kindle_pos, start)
    window = pdf.kindle_text[max(0, begin - 2000):begin + len(pdf.pages[item['page']]) + 2000]
    if window.count(needle) == 1:
        index = max(0, begin - 2000) + window.index(needle)
    elif pdf.kindle_text.count(needle) == 1:
        index = pdf.kindle_text.index(needle)
    else:
        raise ValueError('Highlighted text is not unique in the Kindle book')
    return pdf.kindle_pos[index], pdf.kindle_pos[index + len(needle) - 1]


def kindle_state(modules, book, offset):
    ksdk = modules['ksdk']
    annotations = ksdk.load_existing_annotations(ksdk.find_ksdk_db(), book.dataset_id)
    highlights, notes = {}, {}
    for a in annotations:
        if a.source == 'nonsyncable_annotations':
            continue
        metadata = a.payload.get('json_metadata', {})
        metadata = json.loads(metadata) if isinstance(metadata, str) else metadata
        if a.dataset in (1, 12):
            highlights.setdefault(a.annotation_id, {'id': a.annotation_id, 'start': a.start, 'end': a.end,
                                                    'color': metadata.get('mchl_color'), 'underline': a.dataset == 12})
        elif a.dataset == 3:
            notes[a.start] = (metadata.get('note_text') or '').strip() or None
    for h in highlights.values():
        h['note'] = notes.get(h['end'] + offset)
    return highlights


def value(item):
    return {'color': item['color'], 'underline': item['underline'], 'note': item['note']}


def highlight_changes(modules, cfg, apple_id, kindle_id, baseline):
    book, reader, pdf, path, annotations, kindle_db = open_pair(modules, apple_id, kindle_id)
    capture = json.loads(Path(cfg['capture']).expanduser().read_text())
    kindle = kindle_state(modules, book, capture['note_offset'])
    links = {link['apple']: link for link in baseline.get('highlights', [])}
    changes, seen = [], set()
    for item in apple_highlights(path):
        seen.add(item['key'])
        base = {'id': 'pdf:' + item['key'], 'text': item['text'][:200], 'target': 'kindle',
                'supported': True, 'selected': True, 'apple_ids': [item['key']], 'apple_value': value(item),
                'pdf_highlight': item}
        try:
            start, end = locate(pdf, item)
        except ValueError as exc:
            changes.append(dict(base, kind='add', supported=False, selected=False, reason=str(exc)))
            continue
        match = [k for k in kindle.values() if k['start'] == start and k['end'] == end]
        if not match:
            if any(max(start, k['start']) <= min(end, k['end']) for k in kindle.values()):
                changes.append(dict(base, kind='add', supported=False, selected=False,
                                    reason='Another Kindle highlight overlaps this passage'))
            else:
                changes.append(dict(base, kind='add', start=start, end=end))
            continue
        k = match[0]
        current = {'color': k['color'], 'underline': k['underline'], 'note': k['note']}
        if current != value(item):
            changes.append(dict(base, kind='update', kindle_ids=[k['id']], kindle_value=current))
    for key, link in links.items():
        if key not in seen and link['kindle'] in kindle:
            changes.append({'id': 'pdf-delete:' + key, 'kind': 'delete', 'target': 'kindle', 'text': link.get('text', '')[:200],
                            'supported': True, 'selected': True, 'kindle_ids': [link['kindle']], 'apple_value': None})
    return changes


def add_highlights(modules, cfg, kindle_id, items):
    """Write new Kindle highlights (and notes) for PDF highlights."""
    ksdk = modules['ksdk']
    book = [b for b in ksdk.load_kindle_books() if b.bookid == kindle_id and b.guid][0]
    capture = json.loads(Path(cfg['capture']).expanduser().read_text())
    rows = []
    for item in items:
        created = int((item.get('updated') or time.time()) * 1000)
        ann_id, dataset, payload = ksdk.make_highlight(book, item['start'], item['end'], item['color'], created,
                                                       underline=item['underline'])
        rows.append((ann_id, dataset, book.dataset_id, payload, created))
        if item['note']:
            nid, ndataset, npayload = ksdk.make_note(book, item['end'] + capture['note_offset'], item['note'], created)
            rows.append((nid, ndataset, book.dataset_id, npayload, created))
    if not rows:
        return {'inserted_rows': 0}
    quit_app('Amazon Kindle', 'Kindle')
    db = ksdk.find_ksdk_db()
    saved = backup(Path(db), 'kindle-')
    inserted = ksdk.insert_local_edits(db, rows, capture)
    subprocess.run(['open', '-g', '-a', cfg['kindle_app']], capture_output=True)
    return {'inserted_rows': inserted, 'backup': saved}


def highlight_baseline(modules, cfg, apple_id, kindle_id):
    book, reader, pdf, path, annotations, kindle_db = open_pair(modules, apple_id, kindle_id)
    capture = json.loads(Path(cfg['capture']).expanduser().read_text())
    kindle = kindle_state(modules, book, capture['note_offset'])
    links = []
    for item in apple_highlights(path):
        try:
            start, end = locate(pdf, item)
        except ValueError:
            continue
        match = [k for k in kindle.values() if k['start'] == start and k['end'] == end]
        if match:
            links.append({'apple': item['key'], 'kindle': match[0]['id'], 'text': item['text'][:200]})
    return links
