"""Reuse clippyconvert's Apple writer while preserving native Kindle colors."""
import contextlib
from datetime import datetime
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

from .annotation_colors import apple_style
from .apple import discover, file_status, snapshot
from .native_highlights import runtime


def transfer(config, asset_id, kindle_id, backup_dir, apply=False):
    cfg, modules = runtime(config)
    from clippy.parse_clippings import Clipping
    ksdk = modules['ksdk']
    selected = [b for b in ksdk.load_kindle_books() if b.bookid == kindle_id]
    if len(selected) != 1 or not selected[0].guid:
        raise ValueError('Select one downloaded Kindle cloud book by its exact book ID')
    book = selected[0]
    library, annotations = discover()
    if annotations is None:
        raise ValueError('Apple Books annotation database is missing')
    with snapshot(library) as db:
        books = db.execute('SELECT ZASSETID,ZTITLE,ZAUTHOR,ZPATH FROM ZBKLIBRARYASSET WHERE ZASSETID=?',
                           (asset_id,)).fetchall()
    if len(books) != 1:
        raise ValueError('Select exactly one Apple Books asset ID')
    aid, title, author, raw_path = books[0]
    path = file_status(raw_path)['path']
    epub = modules['epub_cfi'].Epub(path)
    for doc in epub.spine:
        epub.load_doc(doc)
    reader = modules['kindle_annots'].open_book(book)
    if reader.text_length != book.maxpos:
        raise ValueError('Parsed positions differ from the Kindle app position space')
    source = [a for a in ksdk.load_existing_annotations(ksdk.find_ksdk_db(), book.dataset_id)
              if a.source == 'server_view' and a.dataset in (1, 12)]
    if not source:
        raise ValueError('The selected Kindle book has no synced highlights')
    with snapshot(annotations) as db:
        existing = [dict(r) for r in db.execute(
            'SELECT ZANNOTATIONUUID,ZANNOTATIONLOCATION,ZANNOTATIONSELECTEDTEXT,ZANNOTATIONSTYLE,'
            'ZANNOTATIONISUNDERLINE FROM ZAEANNOTATION WHERE ZANNOTATIONASSETID=? '
            'AND ZANNOTATIONTYPE=2 AND ZANNOTATIONDELETED=0', (aid,))]
    normalize = lambda s: modules['epub_cfi'].normalize_with_map(s or '')[0]
    clips, entries = [], []
    for a in source:
        metadata = a.payload.get('json_metadata', {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        color = metadata.get('mchl_color')
        style = apple_style(color, a.dataset == 12)
        text = reader.extract_text(a.start, a.end).strip()
        needle = normalize(text)
        if not needle or sum(doc.norm_text.count(needle) for doc in epub.spine) != 1:
            raise ValueError('A source passage is absent or ambiguous in the Apple EPUB')
        loc = epub.find_text(text, min_score=1.0)
        if loc is None or loc.score != 1.0:
            raise ValueError('No exact Apple EPUB passage match')
        hits = [r for r in existing if r['ZANNOTATIONLOCATION'] == loc.cfi
                or normalize(r['ZANNOTATIONSELECTEDTEXT']) == needle]
        entry = {'kindle_annotation_id': a.annotation_id, 'color': color,
                 'apple_style': style, 'cfi': loc.cfi, 'status': 'already_present' if hits else 'ready'}
        entries.append(entry)
        if hits:
            if len(hits) != 1 or hits[0]['ZANNOTATIONSTYLE'] != style or bool(hits[0]['ZANNOTATIONISUNDERLINE']) != (a.dataset == 12):
                raise ValueError('An existing Apple highlight differs; resolve its color or identity before importing')
            entry['apple_uuid'] = hits[0]['ZANNOTATIONUUID']
            continue
        created = a.payload.get('created_time')
        clip = Clipping(title=title, author=author, kind='Underline' if a.dataset == 12 else 'Highlight',
                        page=None, loc_start=a.start, loc_end=a.end,
                        added=datetime.fromtimestamp(created / 1000) if created else None, text=text)
        clip.bridge_color = color
        clips.append(clip)
    report = {'schema_version': 1, 'kind': 'native_apple_highlights', 'apple_asset_id': aid,
              'kindle_book_id': kindle_id, 'entries': entries, 'write_performed': False,
              'summary': {'ready': len(clips), 'already_present': len(entries) - len(clips)},
              'reverse_notes_supported': False, 'device_display_verified': False}
    if not apply or not clips:
        return report
    subprocess.Popen(['osascript', '-e', 'tell application "Books" to quit'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        if subprocess.run(['pgrep', '-x', 'Books'], capture_output=True).returncode:
            break
        time.sleep(0.5)
    else:
        raise ValueError('Books did not close; no writes performed')
    with snapshot(annotations) as db:
        fresh = [dict(r) for r in db.execute(
            'SELECT ZANNOTATIONUUID,ZANNOTATIONLOCATION,ZANNOTATIONSELECTEDTEXT,ZANNOTATIONSTYLE,'
            'ZANNOTATIONISUNDERLINE FROM ZAEANNOTATION WHERE ZANNOTATIONASSETID=? '
            'AND ZANNOTATIONTYPE=2 AND ZANNOTATIONDELETED=0', (aid,))]
    if fresh != existing:
        raise ValueError('Apple annotations changed; create a new plan')
    folder = Path(backup_dir).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=folder, suffix='.sqlite', delete=False) as f:
        backup = Path(f.name)
    with snapshot(annotations) as source_db:
        with sqlite3.connect(backup) as destination:
            source_db.backup(destination)
    # Retain the reviewed upstream writer. Replace only its fixed-yellow choice
    # in memory; its source files on disk stay unchanged and hash-verified.
    upstream = Path(cfg['clippy_root']).expanduser() / 'kindle2books.py'
    code = upstream.read_text()
    expression = 'STYLE_UNDERLINE if is_ul else STYLE_HIGHLIGHT'
    if code.count(expression) != 1:
        raise ValueError('The upstream color expression changed; no writes performed')
    namespace = {'__name__': 'bridge_clippy_reverse', '__file__': str(upstream),
                 'bridge_style': lambda c: apple_style(c.bridge_color, c.kind == 'Underline')}
    exec(compile(code.replace(expression, 'bridge_style(c)'), str(upstream), 'exec'), namespace)
    namespace['ANN_DB'] = str(annotations)
    namespace['load_library'] = lambda: [(aid, title, author, path)]
    namespace['load_kindle_highlights'] = lambda title_filter=None: (clips, [])
    old_args = sys.argv
    log = io.StringIO()
    try:
        sys.argv = ['kindle2books.py', 'sync', '--min-score', '1.0', '--apply']
        with contextlib.redirect_stdout(log):
            namespace['main']()
    finally:
        sys.argv = old_args
    report.update(write_performed=True, backup=str(backup), upstream_log=log.getvalue())
    opened = subprocess.run(['open', '-g', '-a', 'Books', path], capture_output=True)
    report['app_reopened'] = opened.returncode == 0
    return report
