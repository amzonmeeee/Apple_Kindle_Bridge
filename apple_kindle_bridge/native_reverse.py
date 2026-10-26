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


def attached_note(highlight, annotations, offset):
    """Join only a unique native note at the observed endpoint offset."""
    position = highlight.end + offset
    candidates = [a for a in annotations if a.dataset == 3 and a.start == position and a.end == position]
    owners = [a for a in annotations if a.dataset in (1, 12) and a.end + offset == position]
    if not candidates:
        return None
    if len(candidates) != 1 or len(owners) != 1:
        raise ValueError('Native note attachment is ambiguous')
    metadata = candidates[0].payload.get('json_metadata', {})
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    note = metadata.get('note_text')
    if not isinstance(note, str):
        raise ValueError('Native note text is missing')
    return note


def transfer(config, asset_id, kindle_id, backup_dir, apply=False, annotation_id=None):
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
    synced = [a for a in ksdk.load_existing_annotations(ksdk.find_ksdk_db(), book.dataset_id)
              if a.source == 'server_view']
    source = [a for a in synced if a.dataset in (1, 12)]
    if annotation_id:
        source = [a for a in source if a.annotation_id == annotation_id]
    capture = json.loads(Path(cfg['capture']).expanduser().read_text())
    note_offset = capture.get('note_offset')
    if type(note_offset) is not int:
        raise ValueError('A captured note offset is required')
    if not source:
        raise ValueError('The selected Kindle book has no synced highlights')
    with snapshot(annotations) as db:
        existing = [dict(r) for r in db.execute(
            'SELECT ZANNOTATIONUUID,ZANNOTATIONLOCATION,ZANNOTATIONSELECTEDTEXT,ZANNOTATIONSTYLE,'
            'ZANNOTATIONISUNDERLINE,ZANNOTATIONNOTE FROM ZAEANNOTATION WHERE ZANNOTATIONASSETID=? '
            'AND ZANNOTATIONTYPE=2 AND ZANNOTATIONDELETED=0', (aid,))]
    normalize = lambda s: modules['epub_cfi'].normalize_with_map(s or '')[0]
    clips, entries, notes = [], [], []
    for a in source:
        metadata = a.payload.get('json_metadata', {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        color = metadata.get('mchl_color')
        source_note = attached_note(a, synced, note_offset)
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
                 'apple_style': style, 'cfi': loc.cfi, 'note': source_note, 'status': 'already_present' if hits else 'ready'}
        entries.append(entry)
        if hits:
            if len(hits) != 1 or hits[0]['ZANNOTATIONSTYLE'] != style or bool(hits[0]['ZANNOTATIONISUNDERLINE']) != (a.dataset == 12):
                raise ValueError('An existing Apple highlight differs; resolve its color or identity before importing')
            entry['apple_uuid'] = hits[0]['ZANNOTATIONUUID']
            current_note = hits[0]['ZANNOTATIONNOTE'] or ''
            if source_note and current_note and source_note != current_note:
                entry.update(status='refused', reason='Both apps have different notes; refusing overwrite')
            elif source_note and not current_note:
                entry['status'] = 'ready_note'
                notes.append((loc.cfi, source_note))
            continue
        created = a.payload.get('created_time')
        clip = Clipping(title=title, author=author, kind='Underline' if a.dataset == 12 else 'Highlight',
                        page=None, loc_start=a.start, loc_end=a.end,
                        added=datetime.fromtimestamp(created / 1000) if created else None, text=text)
        clip.bridge_color = color
        clips.append(clip)
        if source_note:
            notes.append((loc.cfi, source_note))
    report = {'schema_version': 1, 'kind': 'native_apple_highlights', 'apple_asset_id': aid,
              'kindle_book_id': kindle_id, 'entries': entries, 'write_performed': False,
              'summary': {state: sum(e['status'] == state for e in entries)
                          for state in ('ready', 'ready_note', 'already_present', 'refused')},
              'reverse_notes_supported': True, 'device_display_verified': False}
    if not apply or not (clips or notes) or report['summary']['refused']:
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
            'ZANNOTATIONISUNDERLINE,ZANNOTATIONNOTE FROM ZAEANNOTATION WHERE ZANNOTATIONASSETID=? '
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
    with sqlite3.connect(annotations) as db:
        for cfi, note in notes:
            matches = db.execute(
                'SELECT ZANNOTATIONUUID,ZANNOTATIONNOTE FROM ZAEANNOTATION '
                'WHERE ZANNOTATIONASSETID=? AND ZANNOTATIONLOCATION=? '
                'AND ZANNOTATIONTYPE=2 AND ZANNOTATIONDELETED=0', (aid, cfi)).fetchall()
            if len(matches) != 1:
                raise ValueError('Imported highlight missing or ambiguous; notes not written')
            uuid, old_note = matches[0]
            if old_note and old_note != note:
                raise ValueError('Apple note changed; refusing overwrite')
            if old_note != note:
                modified = time.time() - 978307200
                db.execute('UPDATE ZAEANNOTATION SET ZANNOTATIONNOTE=?, '
                           'ZANNOTATIONMODIFICATIONDATE=?, ZFUTUREPROOFING11=?, '
                           'Z_OPT=COALESCE(Z_OPT,0)+1 WHERE ZANNOTATIONUUID=?',
                           (note, modified, str(modified), uuid))
    report.update(write_performed=True, backup=str(backup), upstream_log=log.getvalue(),
                  inserted_rows=len(clips), notes_written=len(notes))
    opened = subprocess.run(['open', '-g', '-a', 'Books', path], capture_output=True)
    report['app_reopened'] = opened.returncode == 0
    return report
