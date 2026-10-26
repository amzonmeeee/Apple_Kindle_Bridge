"""Experimental local CFI/XPointer conversion, gated by a real CRengine probe.

Only exact source text positions are accepted. Rendering, saved reader settings,
Apple writeback, and device transfer are intentionally outside this module.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

from .epub import Epub, LocationError, parse_cfi, require_local, resolve_cfi, xml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
PROBE = RUNTIME / 'crengine-probe'
ENGINE_COMMIT = 'f335f7a97e240f505bb8a0dfb721fcb7912a7824'


def source_text(epub, endpoint):
    node = xml(epub.read(endpoint['document']))
    for step in endpoint['cfi_steps']:
        if step % 2:
            slot = (step - 1) // 2
            return (node.text if slot == 0 else list(node)[slot - 1].tail) or ''
        node = list(node)[step // 2 - 1]
    raise LocationError('unsupported_engine_position', 'Only text-node positions are verified')


def coordinate(endpoint):
    return (endpoint['document'], endpoint['spine_index'], endpoint['kind'],
            tuple(endpoint['cfi_steps']), endpoint['utf16_offset'])


def converter_cfi(raw, spine_index):
    """Normalize Apple offset-only ranges for Foliate after strict source validation.

    Assertions remain in the raw evidence; the adapter uses the validated spine
    index and numeric steps, since Foliate uses a synthetic /6 package path.
    """
    endpoints = parse_cfi(raw)
    paths = [pair[1] for pair in endpoints]
    if any(path.side_bias for pair in endpoints for path in pair):
        raise LocationError('unsupported_side_bias', 'Resume-side semantics are not verified')
    prefix = '/6/' + str(2 * (spine_index + 1)) + '!'

    def tail(path, start=0):
        result = ''.join('/' + str(s.number) for s in path.steps[start:])
        if path.offset is not None:
            result += ':' + str(path.offset)
        return result

    if len(paths) == 1:
        # The vendored converter's point branch expects an Element but Foliate
        # returns a Text node for these CFIs. Its Range branch supports Text.
        # An empty range has exactly the same source position as the point.
        point = paths[0]
        parent = ''.join('/' + str(s.number) for s in point.steps[:-1])
        leaf = tail(point, len(point.steps) - 1)
        if point.offset is None:
            leaf += ':0'
        return 'epubcfi(' + prefix + parent + ',' + leaf + ',' + leaf + ')'
    common = 0
    while common < min(len(p.steps) for p in paths) - 1:
        if paths[0].steps[common].number != paths[1].steps[common].number:
            break
        common += 1
    shared = ''.join('/' + str(s.number) for s in paths[0].steps[:common])
    return 'epubcfi(' + prefix + shared + ',' + ','.join(tail(p, common) for p in paths) + ')'


def package_epub(epub):
    """Create a deterministic private ZIP copy; never modify the original EPUB."""
    folder = RUNTIME / 'books'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if epub.archive:
        names = [x.filename for x in epub.archive.infolist() if not x.is_dir()]
    else:
        names = []
        for directory, subdirs, files in os.walk(epub.path, followlinks=False):
            require_local(Path(directory))
            for name in subdirs:
                child = Path(directory) / name
                if child.is_symlink():
                    raise LocationError('unsafe_resource_path', 'Directory symlinks are unsupported')
                require_local(child)
            names.extend((Path(directory) / f).relative_to(epub.path).as_posix() for f in files)
    if len(names) > 10000 or len(names) != len(set(names)):
        raise LocationError('unsupported_archive', 'Too many or duplicate EPUB resources')
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, suffix='.epub', delete=False) as f:
            temp = Path(f.name)
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(zipfile.ZipInfo('mimetype'), b'application/epub+zip')
            total = 0
            for name in sorted(set(names) - {'mimetype'}):
                data = epub.read(name)
                total += len(data)
                if total > 256 * 1024 * 1024:
                    raise LocationError('resource_too_large', 'EPUB exceeds verification size limit')
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
        digest = hashlib.sha256(temp.read_bytes()).hexdigest()
        destination = folder / (digest + '.epub')
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise LocationError('archive_hash_mismatch', 'Existing private EPUB copy changed')
        else:
            os.link(temp, destination)
        return destination, digest
    finally:
        if temp:
            temp.unlink(missing_ok=True)


def run_converter(request):
    proc = subprocess.run(['node', '--disable-warning=ExperimentalWarning',
                           str(ROOT / 'tools/convert-position.mjs')],
                          input=json.dumps([request]), text=True, capture_output=True, timeout=30)
    if proc.returncode:
        raise LocationError('converter_failed', 'DOM conversion process failed; check local runtime installation')
    result = json.loads(proc.stdout)[0]
    if 'error' in result:
        raise LocationError('converter_failed', result['error'])
    return result


def run_engine(book, pointers):
    if not PROBE.is_file():
        raise LocationError('engine_unavailable', 'Build the isolated CRengine probe first')
    if any(not p.startswith('/') or len(p) > 16384 for p in pointers):
        raise LocationError('invalid_xpointer', 'Expected a bounded absolute XPointer')
    proc = subprocess.run([str(PROBE), str(book), *pointers], text=True,
                          capture_output=True, timeout=60)
    if proc.returncode:
        raise LocationError('engine_failed', 'CRengine could not import or inspect this EPUB')
    # CRengine may log informational messages before the probe JSON.
    lines = [line for line in proc.stdout.splitlines() if line.startswith('{"dom_version":')]
    if len(lines) != 1:
        raise LocationError('engine_failed', 'Unexpected CRengine output')
    return json.loads(lines[0])


def validate_engine_point(epub, expected, actual):
    if not actual.get('resolved') or not actual.get('is_text'):
        raise LocationError('engine_position_unresolved', 'Engine did not resolve a text position')
    raw_text = source_text(epub, expected)
    if actual['node_text'] != raw_text:
        raise LocationError('engine_text_normalized', 'Engine/source text differs; exact mapping is not established')
    offset = expected['utf16_offset']
    try:
        prefix = raw_text.encode('utf-16-le')[:offset * 2].decode('utf-16-le')
    except UnicodeDecodeError:
        raise LocationError('split_surrogate', 'CFI splits a Unicode surrogate pair')
    if actual['offset_codepoints'] != len(prefix):
        raise LocationError('engine_offset_mismatch', 'Engine offset differs from the source Unicode position')
    returned = resolve_cfi(epub.path, actual['cfi'])
    if not returned['status'].startswith('resolved_source_') or coordinate(returned['endpoints'][0]) != coordinate(expected):
        raise LocationError('engine_cfi_mismatch', 'Engine-exported CFI does not resolve to the original source coordinate')
    return {'canonical_xpointer': actual['canonical'], 'engine_cfi': actual['cfi'],
            'offset_codepoints': actual['offset_codepoints'],
            'text_sha256': hashlib.sha256(raw_text.encode()).hexdigest(),
            'source_coordinate': expected}


def convert_cfi(path, raw):
    source = resolve_cfi(path, raw)
    report = {'schema_version': 1, 'direction': 'apple_cfi_to_koreader', 'cfi_raw': raw,
              'source': source, 'reader_resume_verified': False, 'write_performed': False}
    epub = None
    try:
        if not source['status'].startswith('resolved_source_'):
            raise LocationError('source_unresolved', source['status'])
        points = source['endpoints']
        if any(p['kind'] != 'text' for p in points) or len({p['document'] for p in points}) != 1:
            raise LocationError('unsupported_engine_position', 'Verification currently requires text endpoints in one document')
        epub = Epub(path)
        adapted = converter_cfi(raw, points[0]['spine_index'])
        converted = run_converter({'xml': epub.read(points[0]['document']).decode('utf-8'),
                                   'spine_index': points[0]['spine_index'], 'cfi': adapted})
        report['converter_candidate'] = converted
        reverse = resolve_cfi(path, converted['reverse_cfi'])
        if not reverse['status'].startswith('resolved_source_') or [coordinate(p) for p in reverse['endpoints']] != [coordinate(p) for p in points]:
            raise LocationError('converter_roundtrip_mismatch', 'Converter round-trip changed source coordinates')
        book, digest = package_epub(epub)
        pointers = [converted['xpointer']] if len(points) == 1 else [converted['pos0'], converted['pos1']]
        engine = run_engine(book, pointers)
        verified = [validate_engine_point(epub, p, e) for p, e in zip(points, engine['results'])]
        if len(verified) != len(points):
            raise LocationError('engine_failed', 'Missing engine results')
        # Recheck inspected source resources, so a concurrently changed EPUB cannot
        # silently mix source validation with a different packaged document.
        final = resolve_cfi(path, raw)
        if final != source:
            raise LocationError('source_changed', 'Source EPUB changed during validation')
        report.update(status='verified_engine_source_position', xpointer=pointers[0],
                      endpoints=verified, normalized_converter_cfi=adapted,
                      epub_copy_sha256=digest, engine_commit=ENGINE_COMMIT,
                      engine_binary_sha256=hashlib.sha256(PROBE.read_bytes()).hexdigest(),
                      dom_version=engine['dom_version'], engine_rendered=engine['rendered'])
    except LocationError as exc:
        report.update(status=exc.code, detail=str(exc))
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        report.update(status='conversion_unavailable', detail=str(exc))
    finally:
        if epub:
            epub.close()
    return report


def convert_xpointer(path, xpointer, end_xpointer=None):
    """Reverse conversion accepts only coordinates independently validated by CRE."""
    epub = None
    base = {'schema_version': 1, 'direction': 'koreader_to_apple_cfi',
            'input_xpointer': xpointer, 'input_end_xpointer': end_xpointer,
            'reader_resume_verified': False, 'write_performed': False}
    try:
        epub = Epub(path)
        book, _ = package_epub(epub)
        pointers = [xpointer] + ([end_xpointer] if end_xpointer else [])
        engine = run_engine(book, pointers)
        exported = [resolve_cfi(path, r.get('cfi')) for r in engine['results']]
        if any(not r['status'].startswith('resolved_source_') for r in exported):
            raise LocationError('engine_cfi_mismatch', 'Engine CFI does not resolve in source')
        points = [r['endpoints'][0] for r in exported]
        if len({p['document'] for p in points}) != 1:
            raise LocationError('unsupported_engine_position', 'Cross-document range is unsupported')
        for p, r in zip(points, engine['results']):
            validate_engine_point(epub, p, r)
        converted = run_converter({'xml': epub.read(points[0]['document']).decode('utf-8'),
                                   'spine_index': points[0]['spine_index'], 'xpointer': xpointer,
                                   'end_xpointer': end_xpointer})
        result = convert_cfi(path, converted['cfi'])
        if result['status'] != 'verified_engine_source_position':
            return {**base, 'status': result['status'], 'detail': 'Reverse CFI failed forward verification', 'verification': result}
        if [coordinate(p) for p in result['source']['endpoints']] != [coordinate(p) for p in points]:
            raise LocationError('converter_roundtrip_mismatch', 'Reverse conversion changed source coordinates')
        return {**result, **base, 'cfi': converted['cfi']}
    except LocationError as exc:
        return {**base, 'status': exc.code, 'detail': str(exc)}
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        return {**base, 'status': 'conversion_unavailable', 'detail': str(exc)}
    finally:
        if epub:
            epub.close()
