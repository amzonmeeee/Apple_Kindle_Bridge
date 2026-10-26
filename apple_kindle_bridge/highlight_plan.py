"""Prepare one-book annotation previews with the existing Readest/CRengine adapter."""
from collections import Counter

from .koreader import convert_cfi
from .kosync import matching_reader_file
from .sync import digest


def preview_highlights(export, asset_id, epub_path, reader_file):
    if export.get('kind') != 'apple_books_highlights' or export.get('schema_version') != 1:
        raise ValueError('Supply an Apple Books highlight export')
    if not isinstance(asset_id, str) or not asset_id:
        raise ValueError('Select one Apple Books asset ID')
    rows = [r for r in export['highlights'] if r.get('asset_id') == asset_id]
    if not rows:
        raise ValueError('The selected book has no records in this highlight export')
    document_id, fingerprint = matching_reader_file(epub_path, reader_file)
    counts = Counter(r.get('uuid') for r in rows)
    records = []
    for row in rows:
        uuid = row.get('uuid')
        item = {'uuid': uuid, 'source_row_id': row.get('row_id'), 'status': 'refused'}
        records.append(item)
        if row.get('deletion_state') != 'active' or row.get('deleted_raw') != 0:
            item.update(status='skipped', reason='Source is deleted or its deletion state is unknown')
            continue
        if not isinstance(uuid, str) or not uuid or counts[uuid] != 1:
            item['reason'] = 'Missing or duplicate source UUID'
            continue
        if row.get('source_issues'):
            item['reason'] = 'Resolve the source issues in the highlight export first'
            continue
        if not isinstance(row.get('text'), str) or not row['text'].strip():
            item['reason'] = 'The source has no selected text'
            continue
        if not isinstance(row.get('location_raw'), str):
            item['reason'] = 'The source has no CFI'
            continue
        result = convert_cfi(epub_path, row['location_raw'], selected_text=row['text'])
        item['verification'] = result
        if result['status'] != 'verified_engine_source_position':
            item['reason'] = result['status']
            continue
        if result['epub_copy_sha256'] != fingerprint:
            raise ValueError('The EPUB changed during highlight verification')
        identity = {'source': 'apple_books', 'asset_id': asset_id, 'uuid': uuid,
                    'target': 'koreader', 'book_sha256': fingerprint}
        payload = {key: row.get(key) for key in
                   ('text', 'note', 'location_raw', 'style_raw', 'underline_raw')}
        item.update(
            status='verified_preview', transfer_id=digest(identity),
            source_revision_sha256=digest(payload), annotation=payload,
            target={'reader': 'koreader', 'document': document_id,
                    'pos0': result['endpoints'][0]['canonical_xpointer'],
                    'pos1': result['endpoints'][1]['canonical_xpointer'],
                    'dom_version': result['dom_version']})
    final_document, final_fingerprint = matching_reader_file(epub_path, reader_file)
    if (final_document, final_fingerprint) != (document_id, fingerprint):
        raise ValueError('The reader EPUB changed while the preview was prepared')
    return {
        'schema_version': 1, 'kind': 'highlight_transfer_preview',
        'source_export_sha256': digest(export),
        'book_link': {'apple_asset_id': asset_id, 'koreader_document': document_id,
                      'epub_copy_sha256': fingerprint, 'selection': 'explicit'},
        'summary': {'records': len(records), **{
            status: sum(r['status'] == status for r in records)
            for status in ('verified_preview', 'refused', 'skipped')}},
        'records': records, 'write_performed': False, 'device_verified': False,
        'limitations': [
            'Only the supplied EPUB pair is checked; no fuzzy edition or title matching is used.',
            'Source selection text and both engine endpoints are checked, not rendered device highlights.',
            'Stable transfer IDs do not prove that a target annotation is absent.',
            'Target annotations must be read before an import can prevent duplicates.',
            'No native Kindle MOBI/KFX mapping, target deletion, or cloud propagation is performed.',
        ],
    }
