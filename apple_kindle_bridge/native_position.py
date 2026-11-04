"""Explicit one-book resume transfer using the existing EPUB and KFX readers.

Mac Kindle shelf positions are written only after the app closes. A local write
and reopen do not establish Whispersync or physical-device acceptance.
"""
import bisect
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time

from . import paths
from .apple import snapshot
from .apple_position import bookmark, selected_book, transfer as write_apple
from .epub import Epub
from .epub import xml
from .koreader import convert_cfi, source_text
from .native_highlights import runtime


def exact_index(mapping, offset):
    index = bisect.bisect_left(mapping, offset)
    if index == len(mapping) or mapping[index] != offset:
        raise ValueError('The position is outside a retained text character')
    return index


def unique_start(haystack, needle):
    if not needle or haystack.count(needle) != 1:
        raise ValueError('The resume passage is absent or ambiguous')
    return haystack.index(needle)


def codepoint_offset(text, utf16_offset):
    try:
        prefix = text.encode('utf-16-le')[:utf16_offset * 2].decode('utf-16-le')
    except UnicodeError as exc:
        raise ValueError('The source position splits a UTF-16 character') from exc
    return len(prefix)


def text_pieces(element, target):
    """Concatenate an element's text in document order; return it and the target's start."""
    pieces, found = [], None

    def walk(node):
        nonlocal found
        if (node, 'text') == target:
            found = sum(map(len, pieces))
        pieces.append(node.text or '')
        for child in node:
            walk(child)
            if (child, 'tail') == target:
                found = sum(map(len, pieces))
            pieces.append(child.tail or '')
    walk(element)
    return ''.join(pieces), found


def context_candidates(epub, point, text, offset):
    """The text node itself, then its enclosing elements, nearest first.

    A short node such as a drop cap ("C") is not unique in the Kindle text, but
    its paragraph is.
    """
    yield text, offset
    chain = [xml(epub.read(point['document']))]
    for step in point['cfi_steps'][:-1]:
        chain.append(list(chain[-1])[step // 2 - 1])
    slot = (point['cfi_steps'][-1] - 1) // 2
    owner = chain[-1]
    target = (owner, 'text') if slot == 0 else (list(owner)[slot - 1], 'tail')
    for ancestor in reversed(chain[-4:]):
        full, start = text_pieces(ancestor, target)
        if start is not None:
            yield full, start + offset


def apple_to_kindle(path, cfi, reader, modules):
    verified = convert_cfi(path, cfi)
    if verified['status'] != 'verified_engine_source_position':
        raise ValueError('Apple CFI failed engine verification: ' + verified['status'])
    point = verified['source']['endpoints'][0]
    epub = Epub(path)
    try:
        node_text = source_text(epub, point)
        node_offset = codepoint_offset(node_text, point['utf16_offset'])
        candidates = list(context_candidates(epub, point, node_text, node_offset))
    finally:
        epub.close()
    normalize = modules['epub_cfi'].normalize_with_map
    for text, offset in candidates:
        norm, mapping = normalize(text)
        if norm and reader.norm_text.count(norm) == 1:
            start = unique_start(reader.norm_text, norm)
            local = exact_index(mapping, offset)
            break
    else:
        start, local, text, offset = anchor_by_following_text(reader, normalize, candidates)
    return finish_apple_to_kindle(reader, start, local, text, offset, verified)


def anchor_by_following_text(reader, normalize, candidates):
    """Place a repeated short text, such as a heading, by the next unique text after it.

    Conversion can drop symbols between them, so the short text is found again by
    searching backward from that unique text, within a short distance.
    """
    node_text, node_offset = candidates[0]
    node_norm, node_map = normalize(node_text)
    node_local = exact_index(node_map, node_offset)
    full_text, full_offset = candidates[-1]
    full_norm, full_map = normalize(full_text)
    begin = bisect.bisect_left(full_map, full_offset)
    for skip in range(len(node_norm), min(len(full_norm) - begin, 3000), 10):
        snippet = full_norm[begin + skip:begin + skip + 60]
        if len(snippet) < 30 or reader.norm_text.count(snippet) != 1:
            continue
        found = reader.norm_text.index(snippet)
        window_start = max(0, found - skip - 200)
        start = reader.norm_text.rfind(node_norm, window_start, found)
        if start >= 0:
            return start, node_local, node_text, node_offset
        break
    raise ValueError('The resume passage is absent or ambiguous')


def finish_apple_to_kindle(reader, start, local, text, offset, verified):
    raw_index = reader.norm_map[start + local]
    target = reader.pos[raw_index]
    if reader.extract_text(target, target) != text[offset]:
        raise ValueError('Native target character differs from the source')
    return target, verified


def kindle_to_apple(path, position, reader, modules):
    raw_index = exact_index(reader.pos, position)
    # Keep context inside one existing KFX text chunk. A window across chapter
    # boundaries cannot occur within one Apple EPUB spine document.
    cache = Path(modules['kfx']._cache_path(reader.path))
    chunks = json.loads(cache.read_text())['chunks']
    containing = [(start, text) for start, text in chunks if start <= position < start + len(text)]
    if len(containing) != 1:
        raise ValueError('The native position has no unique text chunk')
    chunk_start, text = containing[0]
    norm, mapping = modules['epub_cfi'].normalize_with_map(text)
    norm_index = exact_index(mapping, position - chunk_start)
    begin, end = max(0, norm_index - 64), min(len(norm), norm_index + 65)
    passage = norm[begin:end]
    epub = modules['epub_cfi'].Epub(path)
    try:
        for doc in epub.spine:
            epub.load_doc(doc)
        hits = [(doc, doc.norm_text.index(passage)) for doc in epub.spine if passage in doc.norm_text]
        if len(hits) != 1 or hits[0][0].norm_text.count(passage) != 1:
            raise ValueError('Kindle resume passage is absent or ambiguous in the Apple EPUB')
        doc, start = hits[0]
        offset = doc.norm_map[start + norm_index - begin]
        steps, local = epub._point(doc, offset, is_end=False)
        run = next(r for r in doc.runs if r.doc_start <= offset < r.doc_start + len(r.text))
        utf16 = len(run.text[:local].encode('utf-16-le')) // 2
        cfi = 'epubcfi(' + doc.spine_step + '!' + ''.join(str(s) for s in steps) + ':' + str(utf16) + ')'
        verified = convert_cfi(path, cfi)
        if verified['status'] != 'verified_engine_source_position':
            raise ValueError('Mapped CFI failed engine verification: ' + verified['status'])
        if doc.full_text[offset] != reader.stripped[raw_index]:
            raise ValueError('Mapped resume characters differ')
        return cfi, verified
    finally:
        if epub.files.zf:
            epub.files.zf.close()


def prepare(config, asset_id, kindle_id, direction):
    cfg, modules = runtime(config)
    books = [b for b in modules['ksdk'].load_kindle_books() if b.bookid == kindle_id and b.guid]
    if len(books) != 1:
        raise ValueError('Select one downloaded Kindle cloud book')
    book = books[0]
    if not book.is_kfx:
        raise ValueError('Native resume transfer is verified only for KFX cloud books')
    reader = modules['kindle_annots'].open_book(book)
    if reader.text_length != book.maxpos:
        raise ValueError('Kindle position space differs from the parsed book')
    path, annotations = selected_book(asset_id)
    with snapshot(annotations) as db:
        apple = bookmark(db, asset_id, for_write=False)
    kindle_db = Path(modules['ksdk'].LASSEN_DATA) / 'Library/Protected/BookData.sqlite'
    with snapshot(kindle_db) as db:
        rows = [dict(r) for r in db.execute(
            'SELECT Z_PK,Z_OPT,ZBOOKID,ZRAWCURRENTPOSITION,ZLONGCURRENTPOSITION '
            'FROM ZBOOK WHERE ZBOOKID=?', ('A:' + kindle_id + '-0',))]
    if len(rows) != 1:
        raise ValueError('Kindle book row is absent or ambiguous')
    kindle = rows[0]
    if direction == 'kindle':
        target, verified = apple_to_kindle(path, apple['ZANNOTATIONLOCATION'], reader, modules)
    elif direction == 'apple':
        target, verified = kindle_to_apple(path, kindle['ZRAWCURRENTPOSITION'], reader, modules)
    else:
        raise ValueError('Choose apple or kindle as the target')
    report = {'schema_version': 1, 'kind': 'native_position_transfer', 'target': direction,
              'asset_id': asset_id, 'kindle_book_id': kindle_id,
              'observed_apple': apple, 'observed_kindle': kindle,
              'proposed_position': target, 'verified_source': verified,
              'write_performed': False, 'device_resume_verified': False,
              'cloud_position_verified': False,
              'status': 'ready'}
    return report, cfg, kindle_db


def transfer(config, asset_id, kindle_id, direction, backup_dir, apply=False):
    report, cfg, dbpath = prepare(config, asset_id, kindle_id, direction)
    if not apply:
        return report
    if direction == 'kindle' and report['proposed_position'] == report['observed_kindle']['ZRAWCURRENTPOSITION']:
        report['status'] = 'already_present'
        return report
    # A native app saves its final page while closing. Form the write plan from
    # that saved state, rather than treating its normal close as a user conflict.
    process, app = ('Books', 'Books') if direction == 'apple' else ('Kindle', 'Amazon Kindle')
    subprocess.Popen(['osascript', '-e', 'tell application "' + app + '" to quit'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        if subprocess.run(['pgrep', '-x', process], capture_output=True).returncode:
            break
        time.sleep(.5)
    else:
        raise ValueError(app + ' did not close; no writes performed')
    fresh, cfg, dbpath = prepare(config, asset_id, kindle_id, direction)
    source_key = 'observed_kindle' if direction == 'apple' else 'observed_apple'
    source_field = 'ZRAWCURRENTPOSITION' if direction == 'apple' else 'ZANNOTATIONLOCATION'
    if fresh[source_key][source_field] != report[source_key][source_field]:
        raise ValueError('Source position changed while closing the target; create a new plan')
    report = fresh
    if direction == 'apple':
        def source_guard():
            fresh, _, _ = prepare(config, asset_id, kindle_id, direction)
            if fresh['observed_kindle'] != report['observed_kindle'] or fresh['verified_source'] != report['verified_source']:
                raise ValueError('Kindle source position changed; create a new plan')
        result = write_apple(asset_id, report['verified_source'],
                             report['observed_apple']['ZANNOTATIONLOCATION'], backup_dir, apply=True, source_guard=source_guard)
        report.update(write_performed=result['write_performed'], status=result['status'], receipt=result)
        if result['status'] == 'already_present':
            path, _ = selected_book(asset_id)
            report['app_reopened'] = subprocess.run(['open', '-g', '-a', 'Books', path], capture_output=True).returncode == 0
        return report
    report.update(paths.kindle_compatibility(cfg['kindle_app'], {'ZBOOK': dbpath}))
    if report['proposed_position'] == report['observed_kindle']['ZRAWCURRENTPOSITION']:
        report['status'] = 'already_present'
        report['app_reopened'] = subprocess.run(['open', '-g', '-a', cfg['kindle_app']], capture_output=True).returncode == 0
        return report
    folder = Path(backup_dir).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=folder, suffix='.sqlite', delete=False) as f:
        backup = Path(f.name)
    with snapshot(dbpath) as src, sqlite3.connect(backup) as dst:
        src.backup(dst)
    with sqlite3.connect(dbpath) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT Z_PK,Z_OPT,ZBOOKID,ZRAWCURRENTPOSITION,ZLONGCURRENTPOSITION '
                         'FROM ZBOOK WHERE Z_PK=?', (report['observed_kindle']['Z_PK'],)).fetchone()
        if row is None or dict(row) != report['observed_kindle']:
            raise ValueError('Kindle position changed; refusing overwrite')
        db.execute('UPDATE ZBOOK SET ZRAWCURRENTPOSITION=?,ZLONGCURRENTPOSITION=NULL,'
                   'Z_OPT=COALESCE(Z_OPT,0)+1 WHERE Z_PK=?',
                   (report['proposed_position'], row['Z_PK']))
    report.update(write_performed=True, status='written', backup=str(backup))
    from urllib.parse import urlencode
    url = 'kindle://book?' + urlencode({'action': 'open', 'asin': kindle_id, 'type': 'PDOC'})
    report['app_reopened'] = subprocess.run(['open', '-g', url], capture_output=True).returncode == 0
    return report
