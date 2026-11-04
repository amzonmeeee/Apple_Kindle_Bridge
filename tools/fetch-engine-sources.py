"""Download the pinned CRengine build inputs listed in runtime-manifest.json.

Each archive is checked against its recorded SHA-256 and unpacked into
.runtime/src, where tools/build-engine.py expects it. CMake is installed into
.runtime/python. Nothing is installed in system folders.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
manifest = json.loads((ROOT / 'third_party/positions/runtime-manifest.json').read_text())
archives = {'crengine': 'crengine.tar.gz', 'pkgconf': 'pkgconf.tar.xz',
            'xxhash': 'xxhash.tar.gz', 'freetype': 'freetype.tar.gz'}
(RUNTIME / 'downloads').mkdir(parents=True, exist_ok=True)
(RUNTIME / 'src').mkdir(parents=True, exist_ok=True)
for name, archive in archives.items():
    target = RUNTIME / 'downloads' / archive
    if not target.exists():
        print('Downloading', name, flush=True)
        with urllib.request.urlopen(manifest['sources'][name]) as response:
            target.write_bytes(response.read())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != manifest['archives_sha256'][archive]:
        target.unlink()
        sys.exit(f'Checksum mismatch for {archive}')
    with tarfile.open(target) as tar:
        tar.extractall(RUNTIME / 'src', filter='data')
subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', '--target', str(RUNTIME / 'python'),
                'cmake==' + manifest['dependencies']['cmake']], check=True)
print('Engine sources ready in', RUNTIME / 'src')
