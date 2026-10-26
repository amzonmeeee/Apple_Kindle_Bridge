"""Write an engine-verified CFI to one existing Apple reading bookmark."""
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

from .apple import discover, file_status, snapshot
from .koreader import convert_cfi
from .sync import position


def selected_book(asset_id):
    library, annotations = discover()
    if annotations is None:
        raise ValueError('Apple Books annotation database is missing')
    with snapshot(library) as db:
        rows = db.execute('SELECT ZPATH FROM ZBKLIBRARYASSET WHERE ZASSETID=?', (asset_id,)).fetchall()
    if len(rows) != 1:
        raise ValueError('Select one Apple Books asset ID')
    return file_status(rows[0][0])['path'], annotations


def bookmark(db, asset_id):
    rows = db.execute('SELECT Z_PK,Z_OPT,ZANNOTATIONUUID,ZANNOTATIONLOCATION,'
                      'ZANNOTATIONMODIFICATIONDATE,ZFUTUREPROOFING8,ZFUTUREPROOFING10,ZPLUSERDATA '
                      'FROM ZAEANNOTATION WHERE ZANNOTATIONASSETID=? AND ZANNOTATIONTYPE=3 '
                      'AND ZANNOTATIONDELETED=0', (asset_id,)).fetchall()
    if len(rows) != 1:
        raise ValueError('The book must have one active reading-position bookmark')
    row = dict(rows[0])
    if row['ZPLUSERDATA'] is not None:
        raise ValueError('Archived page-data writeback is not verified for this book')
    return row


def write_bookmark(db, asset_id, expected, cfi):
    """Compare inside the write transaction. Keep current/furthest fractions intact."""
    db.execute('BEGIN IMMEDIATE')
    current = bookmark(db, asset_id)
    if current != expected:
        raise ValueError('Apple position changed; create a new plan')
    modified = time.time() - 978307200
    db.execute('UPDATE ZAEANNOTATION SET ZANNOTATIONLOCATION=?,ZANNOTATIONMODIFICATIONDATE=?,'
               'ZFUTUREPROOFING6=?,ZFUTUREPROOFING11=?,Z_OPT=COALESCE(Z_OPT,0)+1 WHERE Z_PK=?',
               (cfi, modified, str(modified), str(modified), current['Z_PK']))


def transfer(asset_id, source_report, expected_cfi, backup_dir, apply=False, source_guard=None):
    source = position(source_report)
    cfi = source_report.get('cfi') or source_report.get('cfi_raw')
    if not cfi:
        raise ValueError('The verified source report has no CFI')
    path, annotations = selected_book(asset_id)
    verified = convert_cfi(path, cfi)
    if position(verified) != source:
        raise ValueError('Source report does not match the target EPUB and engine')
    with snapshot(annotations) as db:
        current = bookmark(db, asset_id)
    if current['ZANNOTATIONLOCATION'] != expected_cfi:
        raise ValueError('Expected Apple position is stale')
    current_verified = convert_cfi(path, expected_cfi)
    same_position = (current_verified.get('status') == 'verified_engine_source_position'
                     and position(current_verified) == source)
    result = {'schema_version': 1, 'kind': 'apple_position_write', 'asset_id': asset_id,
              'source_position': source, 'cfi': cfi, 'expected_cfi': expected_cfi,
              'write_performed': False, 'reader_resume_verified': False,
              'icloud_verified': False, 'high_watermark_preserved': True,
              'status': 'already_present' if same_position else 'ready'}
    if not apply or result['status'] == 'already_present':
        return result
    subprocess.Popen(['osascript', '-e', 'tell application "Books" to quit'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        if subprocess.run(['pgrep', '-x', 'Books'], capture_output=True).returncode:
            break
        time.sleep(0.5)
    else:
        raise ValueError('Books did not close; no writes performed')
    folder = Path(backup_dir).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=folder, suffix='.sqlite', delete=False) as f:
        backup = Path(f.name)
    with snapshot(annotations) as db, sqlite3.connect(backup) as destination:
        if bookmark(db, asset_id) != current:
            raise ValueError('Apple position changed while closing; create a new plan')
        db.backup(destination)
    if position(convert_cfi(path, cfi)) != source:
        raise ValueError('EPUB changed before writing')
    if source_guard is not None:
        source_guard()
    with sqlite3.connect(annotations) as db:
        db.row_factory = sqlite3.Row
        write_bookmark(db, asset_id, current, cfi)
    with snapshot(annotations) as db:
        saved = bookmark(db, asset_id)
    result.update(write_performed=True, status='written', backup=str(backup),
                  database_readback_verified=saved['ZANNOTATIONLOCATION'] == cfi)
    opened = subprocess.run(['open', '-g', '-a', 'Books', path], capture_output=True)
    result['app_reopened'] = opened.returncode == 0
    return result
