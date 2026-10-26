"""Read Apple Books highlights using the existing WAL-aware snapshot helper.

Field semantics reference: seanmatheny/clippyconvert, clippy/books_export.py.
No passage matcher, format converter, or reader writer is implemented here.
"""
from collections import Counter
from datetime import datetime, timezone

from .apple import apple_date, read_rows, snapshot


FIELDS = (
    'Z_PK', 'ZANNOTATIONUUID', 'ZANNOTATIONASSETID', 'ZANNOTATIONTYPE',
    'ZANNOTATIONDELETED', 'ZANNOTATIONSELECTEDTEXT', 'ZANNOTATIONNOTE',
    'ZANNOTATIONLOCATION', 'ZANNOTATIONSTYLE', 'ZANNOTATIONISUNDERLINE',
    'ZANNOTATIONCREATIONDATE', 'ZANNOTATIONMODIFICATIONDATE', 'ZFUTUREPROOFING5',
)
REQUIRED = (
    'Z_PK', 'ZANNOTATIONUUID', 'ZANNOTATIONASSETID', 'ZANNOTATIONTYPE',
    'ZANNOTATIONDELETED', 'ZANNOTATIONSELECTEDTEXT', 'ZANNOTATIONLOCATION',
)


def export_highlights(library, annotations, asset_id=None):
    captured = datetime.now(timezone.utc).isoformat()
    with snapshot(library) as db:
        books, library_schema = read_rows(
            db, 'ZBKLIBRARYASSET', ('Z_PK', 'ZASSETID', 'ZTITLE', 'ZAUTHOR'),
            ('Z_PK', 'ZASSETID', 'ZTITLE'))
    with snapshot(annotations) as db:
        rows, annotation_schema = read_rows(db, 'ZAEANNOTATION', FIELDS, REQUIRED)
    books_by_id = {}
    for book in books:
        books_by_id.setdefault(book['ZASSETID'], []).append({
            'row_id': book['Z_PK'], 'title': book['ZTITLE'], 'author': book.get('ZAUTHOR')})
    rows = [row for row in rows if row['ZANNOTATIONTYPE'] == 2
            and (asset_id is None or row['ZANNOTATIONASSETID'] == asset_id)]
    identities = Counter((row['ZANNOTATIONASSETID'], row['ZANNOTATIONUUID']) for row in rows)
    records = []
    for row in rows:
        aid, uuid = row['ZANNOTATIONASSETID'], row['ZANNOTATIONUUID']
        deleted = row['ZANNOTATIONDELETED']
        deletion_state = 'deleted' if deleted == 1 else 'active' if deleted == 0 else 'unknown'
        issues = []
        if not aid or not uuid:
            issues.append('missing_source_identity')
        if identities[(aid, uuid)] > 1:
            issues.append('duplicate_source_identity')
        if len(books_by_id.get(aid, [])) != 1:
            issues.append('missing_or_ambiguous_library_record')
        if not isinstance(row['ZANNOTATIONSELECTEDTEXT'], str) or not row['ZANNOTATIONSELECTEDTEXT'].strip():
            issues.append('missing_selected_text')
        if deletion_state != 'active':
            issues.append('source_' + deletion_state)
        records.append({
            'row_id': row['Z_PK'], 'asset_id': aid, 'uuid': uuid,
            'books': books_by_id.get(aid, []),
            'deletion_state': deletion_state, 'deleted_raw': deleted,
            'text': row['ZANNOTATIONSELECTEDTEXT'], 'note': row.get('ZANNOTATIONNOTE'),
            'location_raw': row['ZANNOTATIONLOCATION'],
            'style_raw': row.get('ZANNOTATIONSTYLE'),
            'underline_raw': row.get('ZANNOTATIONISUNDERLINE'),
            'chapter_raw': row.get('ZFUTUREPROOFING5'),
            'created_at': apple_date(row.get('ZANNOTATIONCREATIONDATE')),
            'modified_at': apple_date(row.get('ZANNOTATIONMODIFICATIONDATE')),
            'source_issues': issues, 'origin': 'unknown',
            'target_position_verified': False,
        })
    return {
        'schema_version': 1, 'kind': 'apple_books_highlights',
        'captured_at': captured, 'completed_at': datetime.now(timezone.utc).isoformat(),
        'sources': {'library': str(library.resolve()), 'annotations': str(annotations.resolve())},
        'source_schemas': {'library': library_schema, 'annotations': annotation_schema},
        'asset_filter': asset_id, 'read_only': True, 'write_performed': False,
        'summary': {
            'records': len(records),
            **{state: sum(r['deletion_state'] == state for r in records)
               for state in ('active', 'deleted', 'unknown')},
            'with_notes': sum(bool(r['note']) for r in records),
            'without_source_issues': sum(not r['source_issues'] for r in records),
        },
        'limitations': [
            'Each database is a separate snapshot, not an atomic pair.',
            'Text and notes are private. This export is not a transfer preview.',
            'Source CFIs and target positions have not been verified.',
            'Deleted rows are evidence, not instructions to delete target annotations.',
            'The chapter field does not establish the original app or prevent transfer loops.',
        ],
        'highlights': records,
    }
