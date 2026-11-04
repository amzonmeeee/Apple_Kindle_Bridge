"""Per-pair differences between Apple Books and Kindle for Mac.

A baseline records the state after the last sync. A side that differs from it
has changed. Without a baseline, the newer side is the default and every
difference is listed so the user can choose.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

from . import paths
from .annotation_colors import apple_style, kindle_color
from .apple import snapshot
from .apple_position import bookmark, selected_book
from .koreader import source_text
from .epub import Epub
from .native_reverse import NoteAnchor, attached_note, standalone_notes

CORE_DATA_EPOCH = 978307200
# Mac Kindle stores the start of the displayed page when it reopens a book.
# Positions this close are treated as the same place.
POSITION_TOLERANCE = 1500

KINDLE_WRITE_PENDING = ('Kindle for Mac has no captured edit or delete format yet. '
                        'Run the edit capture once to enable this change.')


def baseline_file(apple_id):
    folder = paths.data_dir() / 'baselines'
    folder.mkdir(exist_ok=True, mode=0o700)
    return folder / f'{apple_id}.json'


def load_baseline(apple_id):
    path = baseline_file(apple_id)
    return json.loads(path.read_text()) if path.exists() else {}


def save_baseline(apple_id, data):
    path = baseline_file(apple_id)
    data['saved'] = datetime.now(timezone.utc).isoformat()
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temp.replace(path)


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat() if seconds else None


def clean_note(text):
    return (text or '').strip() or None


class Book:
    """Opened sources for one pair. Opening the KFX text is the slow part."""

    def __init__(self, modules, apple_id, kindle_id):
        self.modules, self.apple_id, self.kindle_id = modules, apple_id, kindle_id
        ksdk = modules['ksdk']
        found = [b for b in ksdk.load_kindle_books() if b.bookid == kindle_id and b.guid]
        if len(found) != 1:
            raise ValueError('Kindle book is not downloaded')
        self.kindle = found[0]
        self.reader = modules['kindle_annots'].open_book(self.kindle)
        if self.reader.text_length != self.kindle.maxpos:
            raise ValueError('Kindle position space differs from the parsed book')
        self.epub_path, self.annotations_db = selected_book(apple_id)
        self.kindle_db = Path(ksdk.LASSEN_DATA) / 'Library/Protected/BookData.sqlite'
        self.ksdk_db = ksdk.find_ksdk_db()
        self.normalize = lambda s: modules['epub_cfi'].normalize_with_map(s or '')[0]

    def kindle_excerpt(self, position, length=80):
        return self.reader.extract_text(position, min(position + length, self.kindle.maxpos)).strip()


def apple_excerpt(path, verified, length=80):
    from .native_position import codepoint_offset, context_candidates
    point = verified['source']['endpoints'][0]
    epub = Epub(path)
    try:
        text = source_text(epub, point)
        offset = codepoint_offset(text, point['utf16_offset'])
        for text, offset in context_candidates(epub, point, text, offset):
            if len(text) - offset >= 20:
                break
    finally:
        epub.close()
    return text[offset:offset + length].strip()


def position_status(book, baseline):
    from .native_position import apple_to_kindle
    with snapshot(book.annotations_db) as db:
        apple = bookmark(db, book.apple_id, for_write=False)
    with snapshot(book.kindle_db) as db:
        row = db.execute('SELECT ZRAWCURRENTPOSITION,ZRAWLASTACCESSTIME FROM ZBOOK WHERE ZBOOKID=?',
                         ('A:' + book.kindle_id + '-0',)).fetchone()
    # A Kindle book that was never opened has no saved position yet.
    kindle_pos, kindle_time = (row[0] or 0) if row else 0, row[1] if row else None
    apple_cfi = apple['ZANNOTATIONLOCATION']
    apple_time = (apple['ZANNOTATIONMODIFICATIONDATE'] or 0) + CORE_DATA_EPOCH
    apple_as_kindle, verified = apple_to_kindle(book.epub_path, apple_cfi, book.reader, book.modules)
    result = {
        'apple': {'cfi': apple_cfi, 'as_kindle_position': apple_as_kindle, 'updated': iso(apple_time),
                  'excerpt': apple_excerpt(book.epub_path, verified)},
        'kindle': {'position': kindle_pos, 'updated': iso(kindle_time),
                   'excerpt': book.kindle_excerpt(kindle_pos),
                   'percent': round(100 * kindle_pos / book.kindle.maxpos, 1) if book.kindle.maxpos else None},
    }
    if abs(apple_as_kindle - kindle_pos) <= POSITION_TOLERANCE:
        result['state'] = 'synced'
        return result
    base = baseline.get('position')
    apple_changed = kindle_changed = True
    if base:
        apple_changed = apple_cfi != base['apple_cfi']
        kindle_changed = abs(kindle_pos - base['kindle_position']) > POSITION_TOLERANCE
    if apple_changed and not kindle_changed:
        direction = 'kindle'
    elif kindle_changed and not apple_changed:
        direction = 'apple'
    else:
        direction = 'kindle' if apple_time >= (kindle_time or 0) else 'apple'
    result.update(state='conflict' if apple_changed and kindle_changed else 'changed',
                  default_target=direction)
    return result


def apple_highlights(book):
    with snapshot(book.annotations_db) as db:
        rows = [dict(r) for r in db.execute(
            'SELECT ZANNOTATIONUUID,ZANNOTATIONSELECTEDTEXT,ZANNOTATIONSTYLE,ZANNOTATIONISUNDERLINE,'
            'ZANNOTATIONNOTE,ZANNOTATIONMODIFICATIONDATE,ZANNOTATIONDELETED FROM ZAEANNOTATION '
            'WHERE ZANNOTATIONASSETID=? AND ZANNOTATIONTYPE=2', (book.apple_id,))]
    found = {}
    for r in rows:
        try:
            color = kindle_color(r['ZANNOTATIONSTYLE'], bool(r['ZANNOTATIONISUNDERLINE']))
        except ValueError:
            color = None
        found[r['ZANNOTATIONUUID']] = {
            'id': r['ZANNOTATIONUUID'], 'text': (r['ZANNOTATIONSELECTEDTEXT'] or '').strip(),
            'key': book.normalize(r['ZANNOTATIONSELECTEDTEXT']), 'color': color,
            'underline': bool(r['ZANNOTATIONISUNDERLINE']), 'note': clean_note(r['ZANNOTATIONNOTE']),
            'updated': (r['ZANNOTATIONMODIFICATIONDATE'] or 0) + CORE_DATA_EPOCH,
            'deleted': bool(r['ZANNOTATIONDELETED'])}
    return found


def kindle_highlights(book, note_offset):
    ksdk = book.modules['ksdk']
    annotations = ksdk.load_existing_annotations(book.ksdk_db, book.kindle.dataset_id)
    import sqlite3
    con = sqlite3.connect(f'file:{book.ksdk_db}?mode=ro', uri=True)
    try:
        times = {}
        for table in ('server_view', 'local_edit'):
            for ann_id, modified in con.execute(
                    f'SELECT annotation_id, modified_time FROM {table} WHERE dataset_id=?',
                    (book.kindle.dataset_id,)):
                times[ann_id] = max(times.get(ann_id, 0), modified or 0)
    finally:
        con.close()
    found = {}
    for a in annotations:
        if a.dataset not in (1, 12) or a.annotation_id in found:
            continue
        metadata = a.payload.get('json_metadata', {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        try:
            note = attached_note(a, annotations, note_offset)
        except ValueError:
            note = None
        text = book.reader.extract_text(a.start, a.end).strip()
        found[a.annotation_id] = {
            'id': a.annotation_id, 'text': text, 'key': book.normalize(text),
            'color': metadata.get('mchl_color'), 'underline': a.dataset == 12,
            'note': clean_note(note), 'updated': times.get(a.annotation_id, 0) / 1000,
            'pending_upload': a.source == 'local_edit'}
    for note in standalone_notes(annotations, note_offset):
        if note.annotation_id in found:
            continue
        anchor = NoteAnchor(note, book.reader)
        text = book.reader.extract_text(anchor.start, anchor.end).strip()
        found[note.annotation_id] = {
            'id': note.annotation_id, 'text': text, 'key': book.normalize(text), 'color': 'yellow',
            'underline': False, 'note': clean_note(anchor.standalone_note),
            'updated': times.get(note.annotation_id, 0) / 1000, 'pending_upload': note.source == 'local_edit',
            'standalone_note': True}
    return found


def content(item):
    return {'color': item['color'], 'underline': item['underline'], 'note': item['note']}


def highlight_changes(book, baseline, note_offset, kindle_edits=False):
    apple = apple_highlights(book)
    kindle = kindle_highlights(book, note_offset)
    links = {link['apple']: link for link in baseline.get('highlights', [])}
    linked_kindle = {link['kindle'] for link in links.values()}
    kindle_by_key = {}
    for k in kindle.values():
        if k['id'] not in linked_kindle:
            kindle_by_key.setdefault(k['key'], []).append(k)
    changes, matched_kindle = [], set()

    def change(kind, item, target, supported=True, **extra):
        if target == 'kindle' and kindle_edits:
            supported = True
        entry = {'id': f'{kind}:{item["id"]}', 'kind': kind, 'target': target, 'text': item['text'][:200],
                 'selected': supported, 'supported': supported}
        if not supported:
            entry['reason'] = KINDLE_WRITE_PENDING
        entry.update(extra)
        changes.append(entry)

    for a in apple.values():
        link = links.get(a['id'])
        k = kindle.get(link['kindle']) if link else None
        if link is None:
            candidates = [] if a['deleted'] else kindle_by_key.get(a['key'], [])
            if len(candidates) == 1:
                k = candidates[0]
                matched_kindle.add(k['id'])
                if content(a) != content(k):
                    newer = 'kindle' if a['updated'] >= k['updated'] else 'apple'
                    change('differs', a, newer, apple_ids=[a['id']], kindle_ids=[k['id']],
                           apple_value=content(a), kindle_value=content(k),
                           supported=newer == 'apple', default_target=newer)
                continue
            if not a['deleted'] and a['key']:
                change('add', a, 'kindle', apple_ids=[a['id']], apple_value=content(a))
            continue
        matched_kindle.add(link['kindle'])
        if k is not None and not a['deleted'] and content(a) == content(k):
            continue  # both sides already agree, even if both changed
        a_changed = a['deleted'] or content(a) != link['apple_value']
        k_changed = k is None or content(k) != link['kindle_value']
        if not a_changed and not k_changed:
            continue
        if a['deleted'] and k is None:
            continue
        if a_changed and not k_changed:
            if a['deleted']:
                change('delete', a, 'kindle', supported=False, kindle_ids=[link['kindle']])
            else:
                change('update', a, 'kindle', supported=False, kindle_ids=[link['kindle']],
                       apple_value=content(a), kindle_value=content(k))
        elif k_changed and not a_changed:
            if k is None:
                change('delete', a, 'apple', apple_ids=[a['id']])
            else:
                change('update', a, 'apple', apple_ids=[a['id']], kindle_ids=[k['id']],
                       apple_value=content(a), kindle_value=content(k))
        else:
            newer = 'kindle' if a['updated'] >= (k['updated'] if k else 0) else 'apple'
            change('conflict', a, newer, apple_ids=[a['id']], kindle_ids=[link['kindle']],
                   apple_value=None if a['deleted'] else content(a),
                   kindle_value=content(k) if k else None,
                   supported=newer == 'apple', default_target=newer)
    for k in kindle.values():
        if k['id'] in matched_kindle or k['id'] in linked_kindle:
            continue
        if k['key']:
            change('add', k, 'apple', kindle_ids=[k['id']], kindle_value=content(k),
                   standalone_note=k.get('standalone_note', False))
    for k_id in linked_kindle - set(kindle):
        pass  # handled above through the Apple side of the link
    return changes, apple, kindle


def pdf_pair_status(modules, apple_id, kindle_id, baseline):
    from . import pdf_position
    result = {'apple_id': apple_id, 'kindle_id': kindle_id, 'has_baseline': bool(baseline), 'pdf': True,
              'highlights': {'changes': [], 'pdf': True}}
    try:
        result['position'] = pdf_position.status(modules, apple_id, kindle_id, baseline)
    except ValueError as exc:
        result['position'] = {'state': 'error', 'error': str(exc)}
    state = result['position'].get('state')
    result['state'] = 'needs_sync' if state in ('changed', 'conflict') else 'error' if state == 'error' else 'synced'
    return result


def is_pdf(apple_id):
    from .apple_position import selected_book
    try:
        return str(selected_book(apple_id)[0]).lower().endswith('.pdf')
    except ValueError:
        return False


def pair_status(modules, cfg, apple_id, kindle_id):
    baseline = load_baseline(apple_id)
    if is_pdf(apple_id):
        return pdf_pair_status(modules, apple_id, kindle_id, baseline)
    capture = json.loads(Path(cfg['capture']).expanduser().read_text())
    result = {'apple_id': apple_id, 'kindle_id': kindle_id, 'has_baseline': bool(baseline)}
    try:
        book = Book(modules, apple_id, kindle_id)
    except ValueError as exc:
        result.update(state='error', error=str(exc))
        return result
    try:
        result['position'] = position_status(book, baseline)
    except ValueError as exc:
        result['position'] = {'state': 'error', 'error': str(exc)}
    try:
        from .native_highlights import can_edit
        changes, apple, kindle = highlight_changes(book, baseline, capture['note_offset'], can_edit(capture))
        result['highlights'] = {'changes': changes,
                                'apple_count': sum(not a['deleted'] for a in apple.values()),
                                'kindle_count': len(kindle),
                                'pending_upload': sum(k['pending_upload'] for k in kindle.values())}
    except ValueError as exc:
        result['highlights'] = {'state': 'error', 'error': str(exc), 'changes': []}
    position_dirty = result['position'].get('state') in ('changed', 'conflict')
    changes = bool(result['highlights']['changes'])
    errors = result['position'].get('state') == 'error' or result['highlights'].get('state') == 'error'
    # A problem on one side does not block the other: highlights can sync while a
    # position cannot be mapped, and the reverse.
    result['state'] = ('needs_sync' if position_dirty or changes
                       else 'error' if errors
                       else 'waiting_cloud' if result['highlights'].get('pending_upload') else 'synced')
    return result


def record_baseline(modules, cfg, apple_id, kindle_id, keep_position=False):
    """Store the current state of both sides after a sync.

    A link whose two sides still differ keeps its earlier values, so a change
    the user left unselected is listed again next time.
    """
    previous = load_baseline(apple_id)
    if is_pdf(apple_id):
        from . import pdf_position
        position = previous.get('position') if keep_position and previous.get('position') \
            else pdf_position.baseline(modules, apple_id, kindle_id)
        save_baseline(apple_id, {'position': position, 'highlights': []})
        return 0
    old_links = {link['apple']: link for link in previous.get('highlights', [])}
    capture = json.loads(Path(cfg['capture']).expanduser().read_text())
    book = Book(modules, apple_id, kindle_id)
    with snapshot(book.annotations_db) as db:
        apple_pos = bookmark(db, apple_id, for_write=False)['ZANNOTATIONLOCATION']
    with snapshot(book.kindle_db) as db:
        kindle_pos = db.execute('SELECT ZRAWCURRENTPOSITION FROM ZBOOK WHERE ZBOOKID=?',
                                ('A:' + kindle_id + '-0',)).fetchone()[0]
    apple = apple_highlights(book)
    kindle = kindle_highlights(book, capture['note_offset'])
    links, used_kindle, linked_apple = [], set(), set()
    # Keep earlier links whose two sides both still exist. Two highlights on the
    # same sentence would otherwise make the text match ambiguous.
    for link in old_links.values():
        a, k = apple.get(link['apple']), kindle.get(link['kindle'])
        if not a or a['deleted'] or not k:
            continue
        linked_apple.add(a['id'])
        used_kindle.add(k['id'])
        links.append({'apple': a['id'], 'kindle': k['id'], 'apple_value': content(a), 'kindle_value': content(k)}
                     if content(a) == content(k) else link)
    kindle_by_key = {}
    for k in kindle.values():
        if k['id'] not in used_kindle:
            kindle_by_key.setdefault(k['key'], []).append(k)
    for a in apple.values():
        if a['deleted'] or a['id'] in linked_apple:
            continue
        match = kindle_by_key.get(a['key'], [])
        if len(match) == 1:
            k = match[0]
            if content(a) != content(k) and a['id'] in old_links:
                links.append(old_links[a['id']])
            elif content(a) == content(k):
                links.append({'apple': a['id'], 'kindle': k['id'],
                              'apple_value': content(a), 'kindle_value': content(k)})
    position = {'apple_cfi': apple_pos, 'kindle_position': kindle_pos}
    if keep_position and previous.get('position'):
        position = previous['position']
    save_baseline(apple_id, {'position': position, 'highlights': links})
    return len(links)
