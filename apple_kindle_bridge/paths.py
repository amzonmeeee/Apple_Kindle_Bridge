"""Locations of the private runtime and app data.

The Mac app sets AKB_HOME to its Application Support folder. Without it, the
repository's development layout under .runtime/ stays in use.
"""
import os
from pathlib import Path
import plistlib
import shutil
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
TESTED_KINDLE_VERSIONS = {'7.70.1'}


def home():
    value = os.environ.get('AKB_HOME')
    return Path(value).expanduser() if value else None


def runtime_dir():
    base = home()
    return base / 'runtime' if base else ROOT / '.runtime'


def data_dir():
    base = home()
    path = base / 'data' if base else ROOT / 'state' / 'app'
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def backup_dir():
    base = home()
    return base / 'backups' if base else ROOT / 'state' / 'native-backups'


def native_config():
    base = home()
    return base / 'native.json' if base else ROOT / '.runtime' / 'native.json'


def node_binary():
    bundled = runtime_dir() / 'node' / 'bin' / 'node'
    return str(bundled) if bundled.is_file() else (shutil.which('node') or 'node')


def jsdom_module():
    for candidate in (runtime_dir() / 'positions' / 'node_modules' / 'jsdom' / 'lib' / 'api.js',
                      runtime_dir() / 'node' / 'node_modules' / 'jsdom' / 'lib' / 'api.js'):
        if candidate.is_file():
            return candidate
    return None


def probe_binary():
    return runtime_dir() / 'crengine-probe'


KINDLE_COLUMNS = {
    'ZBOOK': {'Z_PK', 'Z_OPT', 'ZBOOKID', 'ZRAWCURRENTPOSITION', 'ZLONGCURRENTPOSITION'},
    'local_edit': {'annotation_id', 'action', 'dataset', 'dataset_id', 'serialized_payload',
                   'dirty_flag', 'created_time', 'modified_time', 'retry_count',
                   'expiration_timestamp', 'sync_behavior'},
}


def kindle_version(app_path):
    info = Path(app_path) / 'Contents' / 'Info.plist'
    return plistlib.loads(info.read_bytes()).get('CFBundleShortVersionString')


def kindle_compatibility(app_path, databases):
    """Check the columns the writers use instead of pinning one app version.

    databases maps a table name to the SQLite file that holds it. A version that
    was not tested is reported, not refused; a missing column is refused.
    """
    version = kindle_version(app_path)
    missing = {}
    for table, db_path in databases.items():
        con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        try:
            columns = {row[1] for row in con.execute(f'PRAGMA table_info({table})')}
        finally:
            con.close()
        absent = KINDLE_COLUMNS[table] - columns
        if absent:
            missing[table] = sorted(absent)
    if missing:
        raise ValueError(f'Kindle {version} changed its database layout: {missing}; no writes performed')
    return {'kindle_version': version, 'kindle_version_tested': version in TESTED_KINDLE_VERSIONS}
