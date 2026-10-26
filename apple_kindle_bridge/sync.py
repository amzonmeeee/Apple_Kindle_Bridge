"""Three-way reconciliation of locally verified positions, without device writes.

Conversion remains in the existing Readest/CRengine adapter. This module only
decides direction from a common baseline; percentages and wall clocks never win.
"""
import hashlib
import json
import re


class SyncError(ValueError):
    pass


def digest(value):
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(data.encode()).hexdigest()


def position(report):
    if report.get('status') != 'verified_engine_source_position':
        raise SyncError('Both sides must supply successfully verified conversion reports')
    book = report.get('epub_copy_sha256', '')
    if not isinstance(book, str) or not re.fullmatch('[a-f0-9]{64}', book):
        raise SyncError('Missing verified EPUB fingerprint')
    points = report.get('endpoints') or []
    if not points:
        raise SyncError('Missing verified source coordinates')
    point = points[0]['source_coordinate']
    if point['kind'] != 'text' or not report.get('xpointer'):
        raise SyncError('Only verified text positions can be reconciled')
    # Resume uses the start of a range. A changing visible-page end does not mean
    # that the reader moved. The original range remains in the input reports.
    coordinate = {k: point[k] for k in ('document', 'spine_index', 'cfi_steps', 'utf16_offset')}
    coordinate['text_sha256'] = points[0]['text_sha256']
    return {'book_sha256': book, 'dom_version': report['dom_version'],
            'coordinate': coordinate, 'position_sha256': digest(coordinate)}


def pair(apple, koreader):
    if apple.get('direction') != 'apple_cfi_to_koreader' or koreader.get('direction') != 'koreader_to_apple_cfi':
        raise SyncError('Supply an Apple-to-KOReader report and a KOReader-to-Apple report in that order')
    a, k = position(apple), position(koreader)
    if a['book_sha256'] != k['book_sha256']:
        raise SyncError('Different EPUB fingerprints; refusing cross-edition synchronization')
    if a['dom_version'] != k['dom_version']:
        raise SyncError('Different CRengine DOM versions; revalidate both positions first')
    return a, k


def baseline(apple, koreader):
    a, k = pair(apple, koreader)
    if a['position_sha256'] != k['position_sha256']:
        raise SyncError('A baseline requires both readers observed at the same source position')
    return {'schema_version': 1, 'kind': 'common_position_baseline', **a,
            'reader_resume_verified': False}


def plan(apple, koreader, common=None, prefer=None):
    a, k = pair(apple, koreader)
    if prefer not in (None, 'apple', 'koreader'):
        raise SyncError('Prefer must be apple or koreader')
    common_hash = None
    if common is not None:
        if common.get('schema_version') != 1 or common.get('kind') != 'common_position_baseline':
            raise SyncError('Unsupported baseline')
        if common.get('book_sha256') != a['book_sha256'] or common.get('dom_version') != a['dom_version']:
            raise SyncError('Baseline belongs to a different book or DOM version')
        common_hash = common.get('position_sha256')
        if not common_hash or common_hash != digest(common.get('coordinate')):
            raise SyncError('Baseline coordinate digest is inconsistent')
    same = a['position_sha256'] == k['position_sha256']
    a_changed = common_hash is not None and a['position_sha256'] != common_hash
    k_changed = common_hash is not None and k['position_sha256'] != common_hash
    source = None
    if same:
        action, reason = 'no_change', 'Both readers are at the same source position'
    elif common_hash is None:
        action, reason = 'choose_initial_source', 'No common baseline; neither side wins automatically'
    elif a_changed and k_changed:
        action, reason = 'conflict', 'Both readers moved since the common baseline'
    elif a_changed:
        action, reason, source = 'apple_to_koreader', 'Only Apple moved, including backward movement', 'apple'
    else:
        action, reason, source = 'koreader_to_apple', 'Only KOReader moved, including backward movement', 'koreader'
    if prefer is not None and action in ('choose_initial_source', 'conflict'):
        source = prefer
        action = 'apple_to_koreader' if prefer == 'apple' else 'koreader_to_apple'
        reason = 'Explicit source selection resolves ' + ('initial state' if common_hash is None else 'conflict')
    result = {'schema_version': 1, 'kind': 'position_sync_plan', 'action': action, 'reason': reason,
              'book_sha256': a['book_sha256'], 'dom_version': a['dom_version'],
              'expected_positions': {'apple': a, 'koreader': k},
              'input_report_sha256': {'apple': digest(apple), 'koreader': digest(koreader)},
              'baseline_sha256': digest(common) if common is not None else None,
              'write_performed': False, 'baseline_advanced': False,
              'limits': ['A plan is not a successful synchronization receipt.',
                         'Re-read both sides before applying; reject stale preconditions.',
                         'Reader settings, Apple databases and historical high-water values are unchanged.']}
    if source:
        selected = apple if source == 'apple' else koreader
        result['proposed_target'] = {
            'side': 'koreader' if source == 'apple' else 'apple',
            'source_position': a if source == 'apple' else k,
            'xpointer': selected['xpointer'],
            'cfi': selected.get('cfi') or selected['cfi_raw'],
            'resume_endpoint': 'start',
            'percentage_policy': 'Do not copy percentages across reader layouts',
            'high_watermark_policy': 'Preserve independently; never use it to select the current position',
        }
    return result


def check_plan(plan_data, apple, koreader):
    """Read-only stale-plan check for the future application step."""
    if plan_data.get('kind') != 'position_sync_plan' or plan_data.get('schema_version') != 1:
        raise SyncError('Unsupported synchronization plan')
    a, k = pair(apple, koreader)
    if plan_data.get('expected_positions') != {'apple': a, 'koreader': k}:
        raise SyncError('Stale plan: reader positions or EPUB identity changed')
    if plan_data.get('input_report_sha256') != {'apple': digest(apple), 'koreader': digest(koreader)}:
        raise SyncError('Stale plan: input evidence changed; create a new plan')
    return {'status': 'preconditions_match', 'write_performed': False}
