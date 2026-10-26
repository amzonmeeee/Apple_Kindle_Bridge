"""One-book Apple Books -> native Kindle imports through local clippyconvert.

The optional upstream dependency supplies all passage, MOBI/KFX and queue code.
This adapter selects explicit book IDs, rejects ambiguity, and backs up writes.
"""
from collections import Counter
import hashlib
import importlib
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import subprocess
import sys
import tempfile
import time

from .apple import snapshot
from .annotation_colors import kindle_color


def runtime(config_path):
    cfg = json.loads(Path(config_path).expanduser().read_text())
    root = Path(cfg['clippy_root']).expanduser().resolve()
    manifest = json.loads((Path(__file__).resolve().parents[1] /
                           'third_party/clippyconvert/manifest.json').read_text())
    if manifest['commit'] != '49dd307fe6132ccdb965c4adb948d30f2287ec34':
        raise ValueError('Use the reviewed clippyconvert revision in docs/native-highlights.md')
    for item in manifest['files']:
        path = (root / item['path']).resolve()
        if root not in path.parents:
            raise ValueError('Invalid upstream source path')
        data = path.read_bytes()
        if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != item['blob_sha']:
            raise ValueError('The reviewed clippyconvert source has changed')
    for key, env in [('calibre_debug', 'CALIBRE_DEBUG'), ('kfx_input_plugin', 'KFX_INPUT_PLUGIN'),
                     ('calibre_config', 'CALIBRE_CONFIG_DIRECTORY')]:
        os.environ[env] = str(Path(cfg[key]).expanduser().resolve())
    sys.path[:0] = [str(root), str(Path(cfg['python_dependencies']).expanduser().resolve())]
    try:
        modules = {name: importlib.import_module('clippy.' + name) for name in
                   ('ksdk', 'kfx', 'kindle_annots', 'books_export', 'epub_cfi', 'textsearch')}
    except ImportError as exc:
        raise ValueError('Install the optional native runtime described in docs/native-highlights.md') from exc
    modules['kfx'].CACHE_DIR = str(Path(cfg['cache_dir']).expanduser().resolve())
    return cfg, modules


def prepare(cfg, modules, asset_id, kindle_id, annotation_uuid=None):
    ksdk = modules['ksdk']
    selected = [b for b in ksdk.load_kindle_books() if b.bookid == kindle_id]
    if len(selected) != 1 or not selected[0].guid:
        raise ValueError('Select one downloaded Kindle cloud book by its exact book ID')
    book = selected[0]
    source = modules['books_export'].load_books_highlights(asset_id)
    if annotation_uuid:
        source = [h for h in source if h.uuid == annotation_uuid]
    if not source or any(not h.uuid for h in source) or max(Counter(h.uuid for h in source).values()) > 1:
        raise ValueError('Source selection is empty or has missing or duplicate UUIDs')
    reader = modules['kindle_annots'].open_book(book)
    if reader.text_length != book.maxpos:
        raise ValueError('Parsed book positions differ from the Kindle app position space')
    db = Path(ksdk.find_ksdk_db())
    existing = ksdk.load_existing_annotations(str(db), book.dataset_id)
    by_id = {}
    for annotation in existing:
        by_id.setdefault(annotation.annotation_id, []).append(annotation)
    normalize = lambda text: modules['epub_cfi'].normalize_with_map(text)[0]
    capture = json.loads(Path(cfg['capture']).expanduser().read_text())
    entries, rows = [], []
    proposed = []
    for h in source:
        entry = {'source_uuid': h.uuid, 'status': 'refused'}
        entries.append(entry)
        try:
            color = kindle_color(h.style, h.is_underline)
        except ValueError as exc:
            entry['reason'] = str(exc)
            continue
        needle = normalize(h.text)
        if not needle or reader.norm_text.count(needle) != 1:
            entry['reason'] = 'Passage is absent or has more than one exact match'
            continue
        hit = modules['textsearch'].find_span(reader.norm_text, needle, min_score=1.0)
        if hit is None or hit[2] != 1.0:
            entry['reason'] = 'No exact passage match'
            continue
        start, end = reader.byte_range_for_norm(hit[0], hit[1])
        if normalize(reader.extract_text(start, end)) != needle:
            entry['reason'] = 'Target position read-back differs from the source text'
            continue
        created = int(h.created.timestamp() * 1000) if h.created else int(time.time() * 1000)
        ann_id, dataset, payload = ksdk.make_highlight(book, start, end, color, created, underline=h.is_underline)
        new_rows = [(ann_id, dataset, book.dataset_id, payload, created)]
        if h.note:
            nid, ndataset, npayload = ksdk.make_note(book, end + capture['note_offset'], h.note, created)
            new_rows.append((nid, ndataset, book.dataset_id, npayload, created))
        ids = [r[0] for r in new_rows]
        entry.update(start=start, end=end, annotation_ids=ids, text=h.text, note=h.note, color=color)
        present = [i for i in ids if i in by_id]
        if present:
            consistent = set(present) == set(ids)
            for target in by_id.get(ann_id, []):
                consistent &= (target.start, target.end, target.dataset) == (start, end, dataset)
                metadata = target.payload.get('json_metadata', {})
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                consistent &= h.is_underline or metadata.get('mchl_color') == color
            if h.note:
                for target in by_id.get(ids[1], []):
                    metadata = target.payload.get('json_metadata', {})
                    if isinstance(metadata, str):
                        metadata = json.loads(metadata)
                    consistent &= metadata.get('note_text') == h.note
            if consistent:
                entry.update(status='already_present', observed_stores=sorted({a.source for i in ids for a in by_id[i]}))
            else:
                entry['reason'] = 'Partial import or changed target content; refusing overwrite'
            continue
        ranges = [(a.start, a.end) for a in existing if a.dataset in (1, 12)] + proposed
        if any(max(start, s) <= min(end, e) for s, e in ranges):
            entry['reason'] = 'Another highlight overlaps this passage'
            continue
        proposed.append((start, end))
        entry['status'] = 'ready'
        rows.extend(new_rows)
    report = {'schema_version': 1, 'kind': 'native_kindle_highlights',
              'apple_asset_id': asset_id, 'kindle_book_id': kindle_id, 'dataset_id': book.dataset_id,
              'entries': entries, 'write_performed': False, 'device_display_verified': False,
              'summary': {state: sum(e['status'] == state for e in entries)
                          for state in ('ready', 'already_present', 'refused')}}
    return report, rows, db, capture


def transfer(config, asset_id, kindle_id, backup_dir, apply=False, annotation_uuid=None):
    cfg, modules = runtime(config)
    report, rows, db, capture = prepare(cfg, modules, asset_id, kindle_id, annotation_uuid)
    if not apply or not rows or report['summary']['refused']:
        return report
    info = plistlib.loads((Path(cfg['kindle_app']) / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleShortVersionString') != capture['kindle_version']:
        raise ValueError('Kindle version changed; capture its native edit format again before writing')
    if not isinstance(capture.get('note_offset'), int):
        raise ValueError('A native note offset capture is required')
    subprocess.Popen(['osascript', '-e', 'tell application "Amazon Kindle" to quit'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        if subprocess.run(['pgrep', '-x', 'Kindle'], capture_output=True).returncode:
            break
        time.sleep(0.5)
    else:
        raise ValueError('Kindle did not close; no writes performed')
    fresh, rows, db, capture = prepare(cfg, modules, asset_id, kindle_id, annotation_uuid)
    if fresh != report:
        raise ValueError('Source or target changed; create a new plan before writing')
    backup_dir = Path(backup_dir).expanduser().resolve()
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=backup_dir, suffix='.sqlite', delete=False) as handle:
        backup = Path(handle.name)
    with snapshot(db) as source:
        with sqlite3.connect(backup) as destination:
            source.backup(destination)
    report['inserted_rows'] = modules['ksdk'].insert_local_edits(str(db), rows, capture)
    report.update(write_performed=True, backup=str(backup), transport_status='queued')
    # A completed database write is reported even if Launch Services cannot open the app.
    opened = subprocess.run(['open', '-a', cfg['kindle_app']], capture_output=True)
    report['app_reopened'] = opened.returncode == 0
    return report
