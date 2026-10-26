"""Read adapter for KOReader's existing progress-sync service.

Protocol: koreader/koreader plugins/kosync.koplugin/api.json and KOSyncClient.lua.
Book key: frontend/util.lua, util.partialMD5. No server or account is created.
"""
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from .epub import Epub, require_local
from .koreader import convert_xpointer, package_epub


class KOSyncError(ValueError):
    pass


def partial_md5(path):
    """KOReader binary matching, including Lua's 32-bit shift behavior at i=-1."""
    path = Path(path).resolve()
    require_local(path)
    checksum = hashlib.md5()
    with path.open('rb') as stream:
        for i in range(-1, 11):
            stream.seek((1024 << ((2 * i) & 31)) & 0xffffffff)
            data = stream.read(1024)
            if not data:
                break
            checksum.update(data)
    return checksum.hexdigest()


def document(epub_path):
    epub = Epub(epub_path)
    try:
        reader_file, fingerprint = package_epub(epub)
    finally:
        epub.close()
    return {'schema_version': 1, 'kind': 'kosync_document', 'reader_file': str(reader_file),
            'document': partial_md5(reader_file), 'epub_copy_sha256': fingerprint,
            'matching_method': 'binary', 'reader_file_must_match': True,
            'network_request_performed': False, 'device_write_performed': False}


def matching_reader_file(epub_path, reader_file):
    source = document(epub_path)
    reader_file = Path(reader_file).expanduser().resolve()
    require_local(reader_file)
    if not reader_file.is_file():
        raise KOSyncError('The reader file must be the exact ZIP EPUB used by KOReader')
    reader = document(reader_file)
    if reader['epub_copy_sha256'] != source['epub_copy_sha256']:
        raise KOSyncError('The Apple EPUB and reader EPUB have different content')
    return partial_md5(reader_file), source['epub_copy_sha256']


def get_progress(server, username, userkey, document_id):
    """One authenticated GET. No redirects, retries, uploads, or credential logs."""
    parts = urlsplit(server)
    if parts.username or parts.password or parts.query or parts.fragment or not parts.hostname:
        raise KOSyncError('Use a server URL without credentials, a query, or a fragment')
    local_http = parts.scheme == 'http' and parts.hostname in ('127.0.0.1', '::1', 'localhost')
    if parts.scheme != 'https' and not local_http:
        raise KOSyncError('Use HTTPS; HTTP is permitted only for a local test server')
    if not isinstance(username, str) or not username or any(ord(c) < 32 or ord(c) > 126 for c in username):
        raise KOSyncError('A nonempty ASCII KOReader username is required')
    if not isinstance(userkey, str) or not re.fullmatch('[a-fA-F0-9]{32}', userkey):
        raise KOSyncError('Set KOSYNC_USERKEY to the KOReader authentication key, not the plain password')
    if not re.fullmatch('[a-f0-9]{32}', document_id):
        raise KOSyncError('Invalid KOReader document key')
    connection_type = http.client.HTTPConnection if local_http else http.client.HTTPSConnection
    connection = connection_type(parts.hostname, parts.port, timeout=15)
    try:
        connection.request('GET', parts.path.rstrip('/') + '/syncs/progress/' + document_id,
                           headers={'Accept': 'application/vnd.koreader.v1+json', 'x-auth-user': username,
                                    'x-auth-key': userkey, 'User-Agent': 'Apple-Kindle-Bridge/0.1'})
        response = connection.getresponse()
        if response.status != 200:
            raise KOSyncError('Progress request failed with HTTP ' + str(response.status))
        body = response.read(65537)
        if len(body) > 65536:
            raise KOSyncError('Progress response exceeds the size limit')
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError):
            raise KOSyncError('The progress service returned invalid JSON') from None
        if not isinstance(data, dict):
            raise KOSyncError('The progress service returned an invalid record')
        pointer = data.get('progress')
        if not isinstance(pointer, str) or not pointer.startswith('/') or len(pointer) > 16384:
            raise KOSyncError('The record does not contain an EPUB XPointer')
        if 'document' in data and data['document'] != document_id:
            raise KOSyncError('The service returned a different document key')
        percentage = data.get('percentage')
        if isinstance(percentage, bool) or not isinstance(percentage, (int, float)) or not math.isfinite(percentage) or not 0 <= percentage <= 1:
            raise KOSyncError('The service returned an invalid percentage')
        # Ignore metadata and unknown fields. Do not persist a response verbatim.
        return {'document': document_id, 'progress': pointer, 'percentage': percentage}
    except (OSError, http.client.HTTPException):
        raise KOSyncError('Cannot read the progress service; check its address and connection') from None
    finally:
        connection.close()


def pull(epub_path, reader_file, dom_version, server=None):
    if dom_version <= 0:
        raise KOSyncError('Supply the DOM version used by the KOReader document')
    server = server or os.environ.get('KOSYNC_SERVER')
    if not server:
        raise KOSyncError('Set KOSYNC_SERVER or supply --server')
    document_id, fingerprint = matching_reader_file(epub_path, reader_file)
    remote = get_progress(server, os.environ.get('KOSYNC_USERNAME'),
                          os.environ.get('KOSYNC_USERKEY'), document_id)
    report = convert_xpointer(epub_path, remote['progress'])
    if report['status'] == 'verified_engine_source_position':
        if report['dom_version'] != dom_version:
            raise KOSyncError('The declared reader DOM version differs from the verification engine')
        if report['epub_copy_sha256'] != fingerprint:
            raise KOSyncError('The EPUB changed during the progress request')
    report['transport'] = {'kind': 'kosync_get_progress', 'server': server.rstrip('/'),
                           'document': document_id, 'reported_percentage': remote['percentage'],
                           'reader_dom_version_declared': dom_version,
                           'reader_dom_version_remote_verified': False,
                           'percentage_used_for_position': False, 'remote_write_performed': False}
    return report
