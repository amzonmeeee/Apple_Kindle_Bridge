"""JSON commands for the Mac app. Run as: python -m apple_kindle_bridge.app <command>.

Each command prints JSON lines. The last line is the result or an error.
"""
from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile

from . import library, paths, runtime_install, sync_status
from .apple import discover, snapshot

KINDLE_APP = Path('/Applications/Amazon Kindle.app')
# Observed: a 158 MB EPUB was refused, so use the documented 50 MB e-mail limit.
SEND_TO_KINDLE_LIMIT = library.SEND_LIMIT
LASSEN = Path.home() / 'Library/Containers/com.amazon.Lassen/Data'


def emit(**event):
    print(json.dumps(event, ensure_ascii=False, default=str), flush=True)


def load_runtime():
    from .native_highlights import runtime
    return runtime(paths.native_config())


def readable(path):
    try:
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        con.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchall()
        con.close()
        return True
    except sqlite3.Error:
        return False


def doctor():
    checks = []

    def check(key, ok, title, detail=None, action=None):
        checks.append({'key': key, 'ok': bool(ok), 'title': title, 'detail': detail, 'action': action})

    components = runtime_install.status()
    missing = [c['label'] for c in components.values() if not c['installed']]
    check('runtime', not missing, 'Bundled tools',
          'Missing: ' + ', '.join(missing) if missing else 'All tools are installed', 'install')
    try:
        apple_db, annotations = discover()
        apple_ok = readable(apple_db) and (annotations is None or readable(annotations))
    except Exception:
        apple_ok = False
    check('apple_access', apple_ok, 'Apple Books data access',
          None if apple_ok else 'Allow Full Disk Access for this app in System Settings', 'full_disk_access')
    check('kindle_app', KINDLE_APP.exists(), 'Kindle for Mac',
          None if KINDLE_APP.exists() else 'Install Kindle from the Mac App Store', 'install_kindle')
    if KINDLE_APP.exists():
        version = paths.kindle_version(KINDLE_APP)
        tested = version in paths.TESTED_KINDLE_VERSIONS
        checks.append({'key': 'kindle_version', 'ok': True, 'warning': not tested,
                       'title': f'Kindle version {version}',
                       'detail': None if tested else 'Not tested yet. Check the first sync on the Kindle device.'})
    book_db = LASSEN / 'Library/Protected/BookData.sqlite'
    kindle_ok = book_db.exists() and readable(book_db)
    check('kindle_access', kindle_ok, 'Kindle data access',
          None if kindle_ok else 'Open Kindle once, then allow Full Disk Access for this app', 'full_disk_access')
    signed_in = bool(glob.glob(str(LASSEN / 'Library/KSDK/amzn1.account.*/ksdk_annotation_v1.db')))
    check('kindle_signed_in', signed_in, 'Kindle account',
          None if signed_in else 'Open Kindle for Mac and sign in', 'open_kindle')
    ready = all(c['ok'] for c in checks)
    return {'ready': ready, 'checks': checks}


def pending_file():
    return paths.data_dir() / 'pending.json'


def load_pending():
    path = pending_file()
    return json.loads(path.read_text()) if path.exists() else []


def save_pending(items):
    pending_file().write_text(json.dumps(items, ensure_ascii=False, indent=2))


def epub_title(path):
    import re
    path = Path(path)
    try:
        if path.is_dir():
            container = (path / 'META-INF/container.xml').read_text(errors='ignore')
            opf = re.search(r'full-path="([^"]+)"', container).group(1)
            text = (path / opf).read_text(errors='ignore')
        else:
            with zipfile.ZipFile(path) as z:
                container = z.read('META-INF/container.xml').decode(errors='ignore')
                opf = re.search(r'full-path="([^"]+)"', container).group(1)
                text = z.read(opf).decode(errors='ignore')
        match = re.search(r'<dc:title[^>]*>(.*?)</dc:title>', text, re.S)
        return match.group(1).strip() if match else None
    except (OSError, KeyError, AttributeError, zipfile.BadZipFile):
        return None


PENDING_DAYS = 3


def resolve_pending(modules):
    """Pair books that arrived on the other side after an import.

    A book that never arrives (a failed send, or one deleted on the other side)
    stops waiting after PENDING_DAYS, or when the user cancels it.
    """
    now = datetime.now(timezone.utc)
    pending = [p for p in load_pending()
               if (now - datetime.fromisoformat(p['created'])).days < PENDING_DAYS]
    if not pending:
        return
    apple = library.apple_books()
    kindle = library.kindle_books(modules)
    paired = library.load_pairs()
    used_apple = {p['apple_asset_id'] for p in paired}
    used_kindle = {p['kindle_book_id'] for p in paired}
    remaining = []

    def done(item):
        if item.get('path'):
            Path(item['path']).unlink(missing_ok=True)

    for item in pending:
        if item.get('apple_id') in used_apple or item.get('kindle_id') in used_kindle:
            pair = next(p for p in paired if item.get('apple_id') == p['apple_asset_id']
                        or item.get('kindle_id') == p['kindle_book_id'])
            queue_carry(pair['apple_asset_id'], pair['kindle_book_id'], item['to'])
            done(item)  # paired already, for example by title
            continue
        titles = {library.norm_title(t) for t in item['titles'] if t}
        if item['to'] == 'kindle':
            hits = [b for b in kindle if b['type'] == 'PDOC' and b['id'] not in used_kindle
                    and library.norm_title(b['title']) in titles]
            if len(hits) == 1:
                library.add_pair(item['apple_id'], hits[0]['id'], 'upload')
                queue_carry(item['apple_id'], hits[0]['id'], 'kindle')
                used_kindle.add(hits[0]['id'])
                done(item)
                continue
        else:
            hits = [b for b in apple if b['id'] not in used_apple and library.norm_title(b['title']) in titles]
            if len(hits) == 1:
                library.add_pair(hits[0]['id'], item['kindle_id'], 'import')
                queue_carry(hits[0]['id'], item['kindle_id'], 'apple')
                used_apple.add(hits[0]['id'])
                done(item)
                continue
        remaining.append(item)
    save_pending(remaining)


# ---- carrying annotations with an imported book ---------------------------

def carry_file():
    return paths.data_dir() / 'carry.json'


def load_carry():
    path = carry_file()
    return json.loads(path.read_text()) if path.exists() else []


def queue_carry(apple_id, kindle_id, to):
    items = [c for c in load_carry() if c['apple_id'] != apple_id]
    items.append({'apple_id': apple_id, 'kindle_id': kindle_id, 'to': to})
    carry_file().write_text(json.dumps(items, indent=2))


def carry():
    """Copy highlights, notes, and the reading position to a newly imported copy.

    Only additions toward the new copy are written; nothing is deleted or
    overwritten. A pair waits in the queue until both copies are ready.
    """
    cfg, modules = load_runtime()
    resolve_pending(modules)
    ready = {(p['apple']['id'], p['kindle']['id']): p for p in library.overview(modules)['pairs'] if p['ready']}
    remaining, done = [], []
    for item in load_carry():
        key = (item['apple_id'], item['kindle_id'])
        if key not in ready:
            remaining.append(item)
            continue
        title = ready[key]['apple']['title']
        emit(event='carrying', title=title)
        try:
            status = sync_status.pair_status(modules, cfg, *key)
            to = item['to']
            changes = [c for c in status.get('highlights', {}).get('changes', [])
                       if c['kind'] == 'add' and c['target'] == to and c['supported']]
            plan = {'apple_id': key[0], 'kindle_id': key[1], 'changes': changes}
            position = status.get('position', {})
            if position.get('state') in ('changed', 'conflict'):
                plan['position'] = to
            else:
                plan['position_synced'] = position.get('state') == 'synced'
            result = apply(plan)
            done.append({'title': title, 'to': to, 'annotations': len(changes),
                         'position': 'position' in plan, 'skipped': result.get('skipped', [])})
        except Exception as exc:
            log_error(['carry', *key])
            remaining.append(item)
            done.append({'title': title, 'to': item['to'], 'error': str(exc)})
    carry_file().write_text(json.dumps(remaining, indent=2))
    return {'carried': done, 'waiting': len(remaining)}


def library_overview():
    cfg, modules = load_runtime()
    resolve_pending(modules)
    result = library.overview(modules)
    result['carry_waiting'] = len(load_carry())
    waiting = {p.get('apple_id') or p.get('kindle_id'): p for p in load_pending()}
    for group in ('apple_only', 'kindle_only'):
        for book in result[group]:
            if book['id'] in waiting:
                book['pending_import'] = waiting[book['id']]['created']
    return result


def status(only=None):
    cfg, modules = load_runtime()
    resolve_pending(modules)
    overview = library.overview(modules)
    results = []
    for pair in overview['pairs']:
        apple_id, kindle_id = pair['apple']['id'], pair['kindle']['id']
        if only and apple_id != only:
            continue
        if not pair['ready']:
            entry = {'apple_id': apple_id, 'kindle_id': kindle_id, 'state': 'unavailable', 'error': pair['reason']}
        else:
            emit(event='checking', title=pair['apple']['title'])
            try:
                entry = sync_status.pair_status(modules, cfg, apple_id, kindle_id)
            except Exception as exc:  # one book must not hide the others
                entry = {'apple_id': apple_id, 'kindle_id': kindle_id, 'state': 'error',
                         'error': f'{type(exc).__name__}: {exc}'}
        entry['title'] = pair['apple']['title']
        entry['author'] = pair['apple']['author']
        results.append(entry)
    return {'pairs': results}


# ---- writes ---------------------------------------------------------------

def quit_app(name, process):
    subprocess.run(['osascript', '-e', f'tell application "{name}" to quit'], capture_output=True)
    for _ in range(120):
        if subprocess.run(['pgrep', '-x', process], capture_output=True).returncode:
            return
        time.sleep(0.5)
    raise ValueError(f'{name} did not close; no writes performed')


def apple_edits(apple_id, edits):
    """Update or soft-delete Apple highlights, the way Apple Books does itself."""
    from .annotation_colors import apple_style
    from .apple_position import selected_book
    path, annotations = selected_book(apple_id)
    quit_app('Books', 'Books')
    folder = paths.backup_dir()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=folder, prefix='apple-', suffix='.sqlite', delete=False) as f:
        backup = Path(f.name)
    with snapshot(annotations) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    now = time.time() - sync_status.CORE_DATA_EPOCH
    with sqlite3.connect(annotations) as db:
        for edit in edits:
            uuid = edit['apple_ids'][0]
            if edit['kind'] == 'delete' or edit.get('kindle_value') is None:
                db.execute('UPDATE ZAEANNOTATION SET ZANNOTATIONDELETED=1, ZANNOTATIONMODIFICATIONDATE=?, '
                           'Z_OPT=COALESCE(Z_OPT,0)+1 WHERE ZANNOTATIONUUID=? AND ZANNOTATIONASSETID=?',
                           (now, uuid, apple_id))
                continue
            value = edit['kindle_value']
            style = apple_style(value['color'], value['underline'])
            # Keeping the Kindle version also restores a highlight deleted in Apple Books.
            db.execute('UPDATE ZAEANNOTATION SET ZANNOTATIONNOTE=?, ZANNOTATIONSTYLE=?, ZANNOTATIONISUNDERLINE=?, '
                       'ZANNOTATIONDELETED=0, ZANNOTATIONMODIFICATIONDATE=?, ZFUTUREPROOFING11=?, '
                       'Z_OPT=COALESCE(Z_OPT,0)+1 WHERE ZANNOTATIONUUID=? AND ZANNOTATIONASSETID=?',
                       (value['note'], style, int(value['underline']), now, str(now), uuid, apple_id))
    subprocess.run(['open', '-g', '-a', 'Books', path], capture_output=True)
    return {'backup': str(backup), 'edited': len(edits)}


def apply(plan):
    from . import native_highlights, native_position, native_reverse
    cfg, modules = load_runtime()
    apple_id, kindle_id = plan['apple_id'], plan['kindle_id']
    config, backups = paths.native_config(), paths.backup_dir()
    results = {'skipped': []}
    changes = plan.get('changes', [])
    to_apple_add = [c for c in changes if c['target'] == 'apple' and c['kind'] == 'add']
    to_apple_edit = [c for c in changes if c['target'] == 'apple' and c['kind'] != 'add']
    to_kindle_add = [c for c in changes if c['target'] == 'kindle' and c['kind'] == 'add']
    to_kindle_edit = [c for c in changes if c['target'] == 'kindle' and c['kind'] != 'add']
    if to_apple_add:
        emit(event='writing', step='Adding highlights to Apple Books')
        ids = [i for c in to_apple_add for i in c['kindle_ids']]
        results['apple_add'] = native_reverse.transfer(config, apple_id, kindle_id, backups, apply=True, annotation_id=ids)
    if to_apple_edit:
        emit(event='writing', step='Updating highlights in Apple Books')
        results['apple_edit'] = apple_edits(apple_id, to_apple_edit)
    if to_kindle_add:
        emit(event='writing', step='Adding highlights to Kindle')
        ids = [i for c in to_kindle_add for i in c['apple_ids']]
        report = native_highlights.transfer(config, apple_id, kindle_id, backups, apply=True, annotation_uuid=ids)
        results['kindle_add'] = report
        if report['summary'].get('refused'):
            results['skipped'].extend({'id': 'add:' + e['source_uuid'], 'reason': e.get('reason')}
                                      for e in report['entries'] if e['status'] == 'refused')
    if to_kindle_edit:
        emit(event='writing', step='Updating highlights in Kindle')
        results['kindle_edit'] = native_highlights.edit(config, kindle_id, to_kindle_edit, backups)
    if plan.get('position') in ('apple', 'kindle'):
        emit(event='writing', step='Moving the reading position')
        results['position'] = native_position.transfer(config, apple_id, kindle_id, plan['position'], backups, apply=True)
    emit(event='writing', step='Saving the sync state')
    results['links'] = sync_status.record_baseline(modules, cfg, apple_id, kindle_id,
                                                   keep_position=plan.get('position') not in ('apple', 'kindle')
                                                   and not plan.get('position_synced'))
    return results


# ---- imports --------------------------------------------------------------

def outbox():
    folder = paths.data_dir() / 'outbox'
    folder.mkdir(exist_ok=True, mode=0o700)
    return folder


def package_for_kindle(apple_ids):
    """Zip Apple Books folders into standard EPUB files for Send to Kindle."""
    books = {b['id']: b for b in library.apple_books()}
    files, pending = [], load_pending()
    for apple_id in apple_ids:
        book = books.get(apple_id)
        if not book or book['kind'] not in ('transferable', 'send_only'):
            raise ValueError(f'Cannot send {book["title"] if book else apple_id}: '
                             + (book.get('reason') if book else 'not found'))
        source = Path(book['path'])
        safe = ''.join(ch for ch in book['title'] if ch not in '/:\\')[:120] or apple_id
        target = outbox() / f'{safe}.epub'
        if book['kind'] == 'send_only':
            target = source  # a PDF file is shared as it is
        elif source.is_dir():
            with zipfile.ZipFile(target, 'w') as z:
                z.write(source / 'mimetype', 'mimetype', compress_type=zipfile.ZIP_STORED)
                for item in sorted(source.rglob('*')):
                    name = item.relative_to(source).as_posix()
                    if item.is_file() and name != 'mimetype' and not name.startswith('iTunesMetadata') \
                            and not item.name.startswith('.'):
                        z.write(item, name, compress_type=zipfile.ZIP_DEFLATED)
        else:
            import shutil
            shutil.copy2(source, target)
        size = target.stat().st_size
        files.append({'apple_id': apple_id, 'title': book['title'], 'path': str(target), 'size': size,
                      'too_large': size > SEND_TO_KINDLE_LIMIT})
        pending = [p for p in pending if p.get('apple_id') != apple_id]
        if book['kind'] == 'send_only':
            continue  # PDFs are sent but never paired
        pending.append({'to': 'kindle', 'apple_id': apple_id, 'path': str(target),
                        'titles': [book['title'], epub_title(target)],
                        'created': datetime.now(timezone.utc).isoformat()})
    save_pending(pending)
    return {'files': files}


def import_to_apple(kindle_ids):
    """Convert downloaded personal Kindle documents to EPUB and add them to Apple Books."""
    cfg, modules = load_runtime()
    books = {b.bookid: b for b in modules['ksdk'].load_kindle_books()}
    calibre = Path(cfg['calibre_debug']).parent / 'ebook-convert'
    env = dict(os.environ, CALIBRE_CONFIG_DIRECTORY=cfg['calibre_config'])
    pending, done = load_pending(), []
    for kindle_id in kindle_ids:
        book = books.get(kindle_id)
        if not book or book.content_type != 'PDOC' or not book.guid:
            raise ValueError(f'{kindle_id}: only downloaded personal documents can be imported')
        sources = sorted(Path(book.path).glob('*.azw8')) or sorted(Path(book.path).glob('*.azw*'))
        if len(sources) != 1:
            raise ValueError(f'{book.title}: book file not found')
        safe = ''.join(ch for ch in book.title if ch not in '/:\\')[:120] or kindle_id
        target = outbox() / f'{safe}.epub'
        emit(event='converting', title=book.title)
        run = subprocess.run([str(calibre), str(sources[0]), str(target)], env=env, capture_output=True, text=True)
        if run.returncode or not target.exists():
            raise ValueError(f'{book.title}: conversion failed')
        subprocess.run(['open', '-g', '-a', 'Books', str(target)], check=True)
        pending = [p for p in pending if p.get('kindle_id') != kindle_id]
        pending.append({'to': 'apple', 'kindle_id': kindle_id, 'path': str(target),
                        'titles': [book.title, epub_title(target)],
                        'created': datetime.now(timezone.utc).isoformat()})
        done.append({'kindle_id': kindle_id, 'title': book.title, 'path': str(target)})
    save_pending(pending)
    return {'imported': done}


def main(argv):
    command, args = argv[0], argv[1:]
    if command == 'doctor':
        return doctor()
    if command == 'library':
        return library_overview()
    if command == 'status':
        return status(args[0] if args else None)
    if command == 'carry':
        return carry()
    if command == 'apply':
        return apply(json.loads(sys.stdin.read()))
    if command == 'package-for-kindle':
        return package_for_kindle(args)
    if command == 'import-to-apple':
        return import_to_apple(args)
    if command == 'pair':
        library.add_pair(args[0], args[1], 'manual')
        return {'paired': args}
    if command == 'unpair':
        library.remove_pair(args[0])
        sync_status.baseline_file(args[0]).unlink(missing_ok=True)
        return {'unpaired': args[0]}
    if command == 'forget-pending':
        keep = []
        for item in load_pending():
            if {item.get('apple_id'), item.get('kindle_id')} & set(args):
                if item.get('path'):
                    Path(item['path']).unlink(missing_ok=True)
            else:
                keep.append(item)
        save_pending(keep)
        return {'forgotten': args}
    raise ValueError('Unknown command: ' + command)


def log_error(argv):
    import traceback
    folder = (paths.home() or paths.ROOT / 'state') / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / 'errors.log', 'a') as log:
        log.write(f"\n== {datetime.now().isoformat()} {' '.join(argv)}\n{traceback.format_exc()}")


if __name__ == '__main__':
    try:
        emit(event='result', result=main(sys.argv[1:]))
    except Exception as exc:
        log_error(sys.argv[1:])
        emit(event='error', message=str(exc), type=type(exc).__name__)
        sys.exit(1)
