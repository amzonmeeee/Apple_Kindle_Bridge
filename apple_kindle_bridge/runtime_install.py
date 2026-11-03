"""First-run download of the private runtime into the app's own folder.

Every download is pinned to a version and checksum. Nothing is installed in
system folders; deleting AKB_HOME removes the runtime completely. The app
downloads Python itself, then runs this module with that Python.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

from . import paths

CLIPPY_COMMIT = '49dd307fe6132ccdb965c4adb948d30f2287ec34'
COMPONENTS = {
    'python': {'label': 'Python 3.12.16',
               'url': 'https://github.com/astral-sh/python-build-standalone/releases/download/20261026/'
                      'cpython-3.12.16%2B20261026-aarch64-apple-darwin-install_only.tar.gz',
               'sha256': 'fbf4afef53c2a6b72bb741bc06d5671a9dfaf87bd84e5aa73ac9b3d0d589f14e'},
    'lxml': {'label': 'lxml 6.1.3', 'version': '6.1.3'},
    'node': {'label': 'Node 24.22.1',
             'url': 'https://nodejs.org/dist/v24.22.1/node-v24.22.1-darwin-arm64.tar.gz',
             'sha256': '89c682593d76cd44233fa53b1563264e7de9cbb189cad169135c5b4fadfbc0a7'},
    'jsdom': {'label': 'jsdom (locked)'},
    'calibre': {'label': 'Calibre 9.17.0',
                'url': 'https://download.calibre-ebook.com/9.17.0/calibre-9.17.0.dmg',
                'sha512': '855411a65ed4e711d570763fa951ac5a0c2eee676ad2e8b316e908f309a1f22298fb89289f2376a07ae3bd95bc21455d5a828ac96bfee7756026171845f85025'},
    'kfx_input': {'label': 'KFX Input 2.34.2',
                  'url': 'https://www.mobileread.com/forums/attachment.php?attachmentid=225470',
                  'sha256': '338809c18e5f9bb721dc3570a64cf6f7add4a1711c8183e6179e90fcbadf3c1d'},
    'clippyconvert': {'label': 'clippyconvert ' + CLIPPY_COMMIT[:7],
                      'url': f'https://github.com/seanmatheny/clippyconvert/archive/{CLIPPY_COMMIT}.tar.gz'},
    'crengine': {'label': 'CRengine probe'},
}


def layout():
    rt = paths.runtime_dir()
    return {
        'python': rt / 'python' / 'bin' / 'python3',
        'lxml': rt / 'pylib' / 'lxml',
        'node': rt / 'node' / 'bin' / 'node',
        'jsdom': rt / 'positions' / 'node_modules' / 'jsdom' / 'lib' / 'api.js',
        'calibre': rt / 'calibre.app' / 'Contents' / 'MacOS' / 'calibre-debug',
        'kfx_input': rt / 'KFX Input.zip',
        'clippyconvert': rt / 'clippyconvert' / 'clippy' / 'ksdk.py',
        'crengine': rt / 'crengine-probe',
    }


def emit(**event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def status():
    found = layout()
    return {name: {'label': COMPONENTS[name]['label'], 'installed': found[name].exists()}
            for name in COMPONENTS}


def download(url, folder, expected):
    target = Path(folder) / 'download'
    # The system curl uses the macOS certificate store; the downloaded Python may not.
    subprocess.run(['/usr/bin/curl', '-fsSL', '--retry', '3', '-o', str(target), url], check=True)
    algorithm, value = expected
    digest = hashlib.new(algorithm, target.read_bytes()).hexdigest()
    if digest != value:
        raise ValueError(f'Checksum mismatch for {url}')
    return target


def extract_tar(archive, destination, strip=1):
    destination = Path(destination)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts[strip:]
            if not parts:
                continue
            member.name = str(Path(*parts))
            tar.extract(member, destination, filter='tar')


def install_python(work):
    spec = COMPONENTS['python']
    archive = download(spec['url'], work, ('sha256', spec['sha256']))
    extract_tar(archive, paths.runtime_dir() / 'python')


def install_lxml(work):
    target = paths.runtime_dir() / 'pylib'
    python = layout()['python']
    subprocess.run([str(python), '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check',
                    '--only-binary', ':all:', '--target', str(target),
                    'lxml==' + COMPONENTS['lxml']['version']], check=True)


def install_node(work):
    spec = COMPONENTS['node']
    archive = download(spec['url'], work, ('sha256', spec['sha256']))
    extract_tar(archive, paths.runtime_dir() / 'node')


def install_jsdom(work):
    folder = paths.runtime_dir() / 'positions'
    folder.mkdir(parents=True, exist_ok=True)
    for name in ('package.json', 'package-lock.json'):
        shutil.copy2(paths.ROOT / 'third_party' / 'positions' / name, folder / name)
    npm = paths.runtime_dir() / 'node' / 'lib' / 'node_modules' / 'npm' / 'bin' / 'npm-cli.js'
    env = dict(os.environ, npm_config_cache=str(Path(work) / 'npm-cache'))
    subprocess.run([str(layout()['node']), str(npm), 'ci', '--prefix', str(folder),
                    '--no-audit', '--no-fund', '--ignore-scripts', '--loglevel=error'], check=True, env=env,
                   stdout=subprocess.DEVNULL)


def install_calibre(work):
    spec = COMPONENTS['calibre']
    image = download(spec['url'], work, ('sha512', spec['sha512']))
    mount = Path(work) / 'mount'
    mount.mkdir()
    subprocess.run(['/usr/bin/hdiutil', 'attach', '-quiet', '-nobrowse', '-readonly',
                    '-mountpoint', str(mount), str(image)], check=True)
    try:
        destination = paths.runtime_dir() / 'calibre.app'
        if destination.exists():
            shutil.rmtree(destination)
        subprocess.run(['/usr/bin/ditto', str(mount / 'calibre.app'), str(destination)], check=True)
    finally:
        subprocess.run(['/usr/bin/hdiutil', 'detach', '-quiet', str(mount)], check=False)


def install_kfx_input(work):
    spec = COMPONENTS['kfx_input']
    archive = download(spec['url'], work, ('sha256', spec['sha256']))
    shutil.move(archive, layout()['kfx_input'])
    # Register the plugin in the app's own Calibre settings for EPUB conversion.
    config = (paths.home() or paths.runtime_dir()) / 'calibre-config'
    config.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(paths.runtime_dir() / 'calibre.app/Contents/MacOS/calibre-customize'),
                    '-a', str(layout()['kfx_input'])], check=True, stdout=subprocess.DEVNULL,
                   env=dict(os.environ, CALIBRE_CONFIG_DIRECTORY=str(config)))


def install_clippyconvert(work):
    spec = COMPONENTS['clippyconvert']
    target = Path(work) / 'clippy.tar.gz'
    subprocess.run(['/usr/bin/curl', '-fsSL', '--retry', '3', '-o', str(target), spec['url']], check=True)
    destination = paths.runtime_dir() / 'clippyconvert'
    extract_tar(target, destination)
    # Blob hashes in the reviewed manifest stand in for the archive checksum.
    manifest = json.loads((paths.ROOT / 'third_party/clippyconvert/manifest.json').read_text())
    for item in manifest['files']:
        data = (destination / item['path']).read_bytes()
        if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != item['blob_sha']:
            shutil.rmtree(destination)
            raise ValueError('clippyconvert source differs from the reviewed revision')


def install_crengine(work):
    resources = os.environ.get('AKB_RESOURCES')
    candidates = [Path(resources) / 'crengine-probe'] if resources else []
    candidates.append(paths.ROOT / '.runtime' / 'crengine-probe')
    source = next((c for c in candidates if c.is_file()), None)
    if source is None:
        raise ValueError('The app bundle is missing its CRengine probe')
    target = layout()['crengine']
    shutil.copy2(source, target)
    target.chmod(0o755)


def write_config():
    rt = paths.runtime_dir()
    base = paths.home() or rt
    capture = base / 'ksdk_capture.json'
    if not capture.exists():
        resources = os.environ.get('AKB_RESOURCES')
        seed = Path(resources) / 'ksdk_capture.json' if resources else None
        if seed and seed.is_file():
            shutil.copy2(seed, capture)
    config = {
        'clippy_root': str(rt / 'clippyconvert'),
        'python_dependencies': str(rt / 'pylib'),
        'calibre_debug': str(layout()['calibre']),
        'calibre_config': str(base / 'calibre-config'),
        'kfx_input_plugin': str(layout()['kfx_input']),
        'cache_dir': str(base / 'cache' / 'kfx'),
        'capture': str(capture),
        'kindle_app': '/Applications/Amazon Kindle.app',
    }
    for key in ('calibre_config', 'cache_dir'):
        Path(config[key]).mkdir(parents=True, exist_ok=True)
    paths.native_config().write_text(json.dumps(config, indent=2))
    return config


STEPS = [('python', install_python), ('lxml', install_lxml), ('node', install_node),
         ('jsdom', install_jsdom), ('calibre', install_calibre), ('kfx_input', install_kfx_input),
         ('clippyconvert', install_clippyconvert), ('crengine', install_crengine)]


def install(only=None):
    if paths.home() is None:
        raise ValueError('Set AKB_HOME before installing the app runtime')
    paths.runtime_dir().mkdir(parents=True, exist_ok=True)
    found = layout()
    for index, (name, step) in enumerate(STEPS, 1):
        if only and name not in only:
            continue
        label = COMPONENTS[name]['label']
        if found[name].exists():
            emit(event='skip', component=name, label=label, step=index, total=len(STEPS))
            continue
        emit(event='start', component=name, label=label, step=index, total=len(STEPS))
        with tempfile.TemporaryDirectory(dir=paths.runtime_dir()) as work:
            step(work)
        emit(event='done', component=name, label=label, step=index, total=len(STEPS))
    write_config()
    emit(event='complete', status=status())


if __name__ == '__main__':
    try:
        install(set(sys.argv[1:]) or None)
    except Exception as exc:  # reported to the app as one JSON line
        emit(event='error', message=str(exc))
        sys.exit(1)
