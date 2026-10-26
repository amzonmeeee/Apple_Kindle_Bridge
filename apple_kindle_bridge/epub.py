"""Offline EPUB CFI inspection. Resolves source documents, not reader-specific positions.

CFI subset and indexing follow https://w3c.github.io/epub-specs/epub33/epubcfi/.
Unsupported constructs fail explicitly; no fuzzy matching or percentage fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import posixpath
import re
import stat
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile


class LocationError(Exception):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(detail)


@dataclass
class Step:
    number: int
    assertion: str | None = None


@dataclass
class CFIPath:
    steps: list[Step]
    offset: int | None = None
    side_bias: str | None = None


def split_cfi(value, separator):
    parts, start, bracket, escaped = [], 0, False, False
    for index, char in enumerate(value):
        if escaped:
            if char not in '^[](),;=':
                raise LocationError('invalid_cfi', 'Invalid CFI escape')
            escaped = False
        elif char == '^':
            escaped = True
        elif char == '[':
            if bracket:
                raise LocationError('invalid_cfi', 'Nested assertion')
            bracket = True
        elif char == ']':
            if not bracket:
                raise LocationError('invalid_cfi', 'Unexpected closing bracket')
            bracket = False
        elif char == separator and not bracket:
            parts.append(value[start:index])
            start = index + 1
    if escaped or bracket:
        raise LocationError('invalid_cfi', 'Unclosed assertion or escape')
    return parts + [value[start:]]


def assertion_value(value):
    parts = split_cfi(value, ';')
    assertion = parts[0]
    bias = None
    if len(parts) > 2 or len(parts) == 2 and parts[1] not in ('s=a', 's=b'):
        raise LocationError('unsupported_assertion_parameter', value)
    if len(parts) == 2:
        bias = parts[1][-1]
    if len(split_cfi(assertion, ',')) > 1:
        raise LocationError('unsupported_text_assertion', 'Text assertions are not silently ignored')
    return re.sub(r'\^(.)', r'\1', assertion), bias


def parse_path(value):
    steps, offset, bias = [], None, None
    index = 0
    while index < len(value):
        token = re.match(r'([/:])(0|[1-9][0-9]*)', value[index:])
        if not token or offset is not None:
            raise LocationError('unsupported_cfi', f'Unsupported path token at {value[index:]}')
        kind, number = token[1], int(token[2])
        index += len(token[0])
        assertion = None
        local_bias = None
        if index < len(value) and value[index] == '[':
            start = index = index + 1
            while index < len(value):
                if value[index] == '^':
                    index += 2
                elif value[index] == ']':
                    break
                else:
                    index += 1
            if index >= len(value):
                raise LocationError('invalid_cfi', 'Unclosed assertion')
            assertion, local_bias = assertion_value(value[start:index])
            index += 1
        if local_bias:
            if index != len(value):
                raise LocationError('unsupported_cfi', 'Side bias must be terminal')
            bias = local_bias
        if kind == ':':
            if assertion:
                raise LocationError('unsupported_text_assertion', 'Text assertion requires a separate validator')
            offset = number
        else:
            if number % 2 and assertion:
                raise LocationError('unsupported_cfi', 'ID assertion on a character-data step')
            steps.append(Step(number, assertion or None))
    if not steps:
        raise LocationError('invalid_cfi', 'A complete path must contain steps')
    return CFIPath(steps, offset, bias)


def parse_cfi(raw):
    if not isinstance(raw, str) or len(raw) > 16384:
        raise LocationError('invalid_cfi', 'Missing or oversized CFI')
    # URI escaping belongs only to the URI form, not a bare CFI string.
    value = raw if raw.startswith('epubcfi(') else unquote(raw.split('#', 1)[1]) if '#' in raw else raw
    if not value.startswith('epubcfi(') or not value.endswith(')'):
        raise LocationError('invalid_cfi', 'Expected epubcfi(...)')
    components = split_cfi(value[8:-1], ',')
    if len(components) not in (1, 3):
        raise LocationError('invalid_cfi', 'Expected a point or a three-part range')
    endpoints = [components[0]] if len(components) == 1 else [components[0] + tail for tail in components[1:]]
    parsed = []
    for endpoint in endpoints:
        indirect = split_cfi(endpoint, '!')
        if len(indirect) != 2:
            raise LocationError('unsupported_indirection', 'Exactly one package-to-document indirection is supported')
        parsed.append((parse_path(indirect[0]), parse_path(indirect[1])))
    if len(parsed) == 2:
        def order(pair):
            return (tuple(s.number for s in pair[0].steps), tuple(s.number for s in pair[1].steps), pair[1].offset or 0)
        if order(parsed[0]) > order(parsed[1]):
            raise LocationError('invalid_range_order', 'Range end precedes start')
    return parsed


def local_name(element):
    return element.tag.rsplit('}', 1)[-1]


def xml(data):
    if b'<!ENTITY' in data.upper():
        raise LocationError('unsupported_xml_entities', 'Custom entity declarations are unsupported')
    try:
        # ElementTree ignores comments and joins their adjacent text, as CFI requires.
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise LocationError('invalid_xml', str(exc)) from exc


def local_member(base, reference):
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise LocationError('unsupported_resource_reference', reference)
    decoded = unquote(parsed.path)
    if not decoded or '\\' in decoded or '\x00' in decoded or decoded.startswith('/'):
        raise LocationError('unsafe_resource_path', reference)
    result = posixpath.normpath(posixpath.join(posixpath.dirname(base), decoded))
    return safe_member(result)


def safe_member(member):
    if not member or '\\' in member or '\x00' in member or member.startswith('/') or member == '..' or member.startswith('../') or posixpath.normpath(member) != member:
        raise LocationError('unsafe_resource_path', member)
    return member


def require_local(path):
    """Check parent directories before touching a possibly evicted iCloud child."""
    for component in [*reversed(path.parents), path]:
        info = component.lstat()
        if getattr(info, 'st_flags', 0) & 0x40000000:
            raise LocationError('not_downloaded', f'iCloud placeholder: {component.name}')
        if stat.S_ISREG(info.st_mode) and info.st_size and getattr(info, 'st_blocks', 1) == 0 and not getattr(info, 'st_flags', 0) & 0x20:
            raise LocationError('not_downloaded', f'File has no local data: {component.name}')


class Epub:
    MAX_MEMBER = 16 * 1024 * 1024

    def __init__(self, path):
        self.path = Path(path).expanduser().absolute()
        require_local(self.path)
        self.path = self.path.resolve()
        self.archive = None
        self.read_hashes = {}
        self.cache = {}
        if not self.path.is_dir():
            self.archive = zipfile.ZipFile(self.path)
        try:
            container = xml(self.read('META-INF/container.xml'))
            files = [e for e in container.iter() if local_name(e) == 'rootfile']
            if not files:
                raise LocationError('missing_package', 'container.xml has no rootfile')
            self.package_path = local_member('', files[0].attrib['full-path'])
            self.package = xml(self.read(self.package_path))
            self.spine = next((e for e in self.package if local_name(e) == 'spine'), None)
            manifest = next((e for e in self.package if local_name(e) == 'manifest'), None)
            if self.spine is None or manifest is None:
                raise LocationError('missing_package', 'Package lacks manifest or spine')
            self.manifest = {}
            for item in manifest:
                key = item.get('id')
                if key in self.manifest:
                    raise LocationError('ambiguous_manifest', f'Duplicate manifest id: {key}')
                self.manifest[key] = item
        except Exception:
            self.close()
            raise

    def close(self):
        if self.archive:
            self.archive.close()

    def read(self, member):
        member = safe_member(member)
        if member in self.cache:
            return self.cache[member]
        if self.archive:
            matches = [entry for entry in self.archive.infolist() if entry.filename == member]
            if len(matches) != 1:
                raise LocationError('missing_or_duplicate_member', member)
            info = matches[0]
            if info.file_size > self.MAX_MEMBER:
                raise LocationError('resource_too_large', member)
            data = self.archive.read(info)
        else:
            candidate = self.path / member
            require_local(candidate)
            resolved = candidate.resolve()
            if self.path not in resolved.parents:
                raise LocationError('unsafe_resource_path', member)
            with resolved.open('rb') as handle:
                data = handle.read(self.MAX_MEMBER + 1)
        if len(data) > self.MAX_MEMBER:
            raise LocationError('resource_too_large', member)
        self.read_hashes[member] = hashlib.sha256(data).hexdigest()
        self.cache[member] = data
        return data

    def content_for(self, package_path):
        if package_path.offset is not None or len(package_path.steps) != 2:
            raise LocationError('unsupported_package_path', 'Expected package → spine → itemref')
        node = self.package
        evidence = []
        for depth, step in enumerate(package_path.steps):
            if step.number <= 0 or step.number % 2 or step.number // 2 > len(node):
                raise LocationError('invalid_package_step', str(step.number))
            node = list(node)[step.number // 2 - 1]
            if (depth == 0 and node is not self.spine) or (depth == 1 and local_name(node) != 'itemref'):
                raise LocationError('invalid_package_step', 'Package path does not select a spine itemref')
            if step.assertion:
                identifier = node.get('id') or node.get('{http://www.w3.org/XML/1998/namespace}id')
                if identifier == step.assertion:
                    continue
                # Observed Apple CFIs assert itemref.idref even when no XML ID exists.
                if depth == 1 and not identifier and node.get('idref') == step.assertion:
                    evidence.append('package_assertion_matches_idref_without_xml_id')
                else:
                    raise LocationError('id_assertion_mismatch', f'Package assertion {step.assertion!r} does not match {identifier!r}')
        item = self.manifest.get(node.get('idref'))
        if item is None:
            raise LocationError('missing_manifest_item', str(node.get('idref')))
        if item.get('media-type') not in ('application/xhtml+xml', 'image/svg+xml'):
            raise LocationError('unsupported_content_type', str(item.get('media-type')))
        member = local_member(self.package_path, item.attrib['href'])
        return member, list(self.spine).index(node), evidence


def utf16_length(text):
    return len(text.encode('utf-16-le')) // 2


def resolve_document(root, cfi_path):
    node = root
    address = []
    text = None
    kind = 'element'
    for index, step in enumerate(cfi_path.steps):
        terminal = index == len(cfi_path.steps) - 1
        address.append(step.number)
        if step.number % 2:
            if not terminal:
                raise LocationError('invalid_cfi', 'Character-data step is not terminal')
            slot = (step.number - 1) // 2
            if slot > len(node):
                raise LocationError('node_out_of_range', f'Text slot {slot}')
            text = (node.text if slot == 0 else list(node)[slot - 1].tail) or ''
            kind = 'text'
        else:
            child = step.number // 2 - 1
            if child in (-1, len(node)) and terminal and step.assertion is None and cfi_path.offset is None:
                kind = 'virtual_before' if child == -1 else 'virtual_after'
                break
            if child < 0 or child >= len(node):
                raise LocationError('node_out_of_range', f'Element step {step.number}')
            node = list(node)[child]
            identifier = node.get('id') or node.get('{http://www.w3.org/XML/1998/namespace}id')
            if step.assertion and identifier != step.assertion:
                raise LocationError('id_assertion_mismatch', f'Content assertion {step.assertion!r} does not match {identifier!r}')
    offset = cfi_path.offset
    if kind == 'element' and offset is not None:
        if local_name(node) == 'img' and 'alt' in node.attrib:
            text, kind = node.attrib['alt'], 'image_alt_text'
        else:
            raise LocationError('unsupported_element_offset', 'Only image alt text accepts element character offsets in standard CFI')
    if text is not None:
        offset = offset or 0
        if offset > utf16_length(text):
            raise LocationError('offset_out_of_range', f'UTF-16 offset {offset} exceeds {utf16_length(text)}')
    return {
        'kind': kind, 'element_tag': local_name(node), 'element_id': node.get('id'),
        'cfi_steps': address, 'utf16_offset': offset, 'side_bias': cfi_path.side_bias,
        'text_utf16_length': utf16_length(text) if text is not None else None,
        'text_sha256': hashlib.sha256(text.encode()).hexdigest() if text is not None else None,
    }


def resolve_cfi(path, raw):
    epub = None
    try:
        endpoints = parse_cfi(raw)
        epub = Epub(path)
        results = []
        for package_path, document_path in endpoints:
            member, index, evidence = epub.content_for(package_path)
            point = resolve_document(xml(epub.read(member)), document_path)
            results.append({'document': member, 'spine_index': index, 'compatibility_notes': evidence, **point})
        return {
            'status': 'resolved_source_range' if len(results) == 2 else 'resolved_source_point',
            'endpoints': results, 'resource_sha256': epub.read_hashes,
            'scope': 'Source EPUB XML only; reader resume behavior and cross-device conversion are unverified.',
        }
    except LocationError as exc:
        return {'status': exc.code, 'detail': str(exc)}
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        return {'status': 'resource_unavailable', 'detail': str(exc)}
    finally:
        if epub:
            epub.close()


def inspect_positions(inventory):
    if inventory.get('schema_version') != 1:
        raise ValueError('Unsupported inventory schema')
    records = []
    for book in inventory['books']:
        for position in book.get('reading_position_records', []):
            if position.get('deleted_raw') == 1:
                continue
            raw = position.get('location_raw')
            file = book['file']
            if not raw:
                result = {'status': 'no_cfi', 'page_data': position.get('page_data')}
            elif file.get('extension') != '.epub' or file['status'] not in ('file', 'directory'):
                result = {'status': 'epub_not_locally_available'}
            else:
                result = resolve_cfi(file['path'], raw)
            records.append({'asset_id': book['asset_id'], 'title': book['title'], 'annotation_row_id': position['row_id'], 'cfi_raw': raw, **result})
    counts = {}
    for record in records:
        counts[record['status']] = counts.get(record['status'], 0) + 1
    return {'schema_version': 1, 'read_only': True, 'summary': counts, 'positions': records,
            'limitations': ['No reader database writes or Kindle/KOReader XPointer output.',
                            'Unsupported CFIs and ID mismatches are reported; no fuzzy recovery.',
                            'Resource hashes cover inspected files, not the entire publication.']}
