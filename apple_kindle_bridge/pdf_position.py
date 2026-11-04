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
        db.execute('UPDATE ZAEANNOTATION SET ZPLUSERDATA=?, ZFUTUREPROOFING10=COALESCE(?,ZFUTUREPROOFING10), '
                   'ZANNOTATIONMODIFICATIONDATE=?, Z_OPT=Z_OPT+1 WHERE Z_PK=?',
                   (blob, fraction, time.time() - 978307200, expected['Z_PK']))


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
    result.update(state='conflict' if apple_changed and kindle_changed else 'changed', default_target=target)
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
        quit_app('Books', 'Books')
        kindle = kindle_row(kindle_db, kindle_id)
        page = pdf.kindle_to_page(kindle['ZRAWCURRENTPOSITION'] or 0)
        with snapshot(annotations) as db:
            apple = apple_page(db, apple_id)
        saved = backup(Path(annotations), 'apple-')
        write_apple_page(annotations, apple_id, apple, page, len(pdf.pages))
        subprocess.run(['open', '-g', '-a', 'Books', path], capture_output=True)
        return {'status': 'written', 'page': page + 1, 'backup': saved}
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
