"""Build the pinned CRengine and minimal dependencies in an isolated temp directory.

Downloaded source archives live in .runtime/downloads; no system installation.
This is a developer verification harness, not a KOReader application build.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
BUILD = Path(tempfile.mkdtemp(prefix='apple-kindle-engine-'))
PREFIX = BUILD / 'prefix'
CMAKE = RUNTIME / 'python/cmake/data/bin/cmake'
env = os.environ.copy()
env['PKG_CONFIG_PATH'] = str(PREFIX / 'lib/pkgconfig')
env['PATH'] = str(PREFIX / 'bin') + os.pathsep + env['PATH']
(RUNTIME / 'engine-build.json').write_text(json.dumps({'build': str(BUILD), 'prefix': str(PREFIX)}, indent=2))


def run(args, cwd=BUILD):
    print('Running:', ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True)


for name in ('pkgconf', 'xxHash', 'freetype', 'crengine'):
    source = next((RUNTIME / 'src').glob(name + '-*'))
    shutil.copytree(source, BUILD / name)

run(['./configure', '--prefix=' + str(PREFIX), '--disable-shared', '--disable-dependency-tracking'], BUILD / 'pkgconf')
run(['make', '-j4'], BUILD / 'pkgconf')
run(['make', 'install'], BUILD / 'pkgconf')


def cmake_build(name, source, options):
    dest = BUILD / (name + '-build')
    run([CMAKE, '-S', source, '-B', dest, '-DCMAKE_BUILD_TYPE=Release',
         '-DCMAKE_INSTALL_PREFIX=' + str(PREFIX), '-DCMAKE_PREFIX_PATH=' + str(PREFIX),
         '-DBUILD_SHARED_LIBS=OFF', *options])
    run([CMAKE, '--build', dest, '-j4'])
    return dest


xx = cmake_build('xxhash', BUILD / 'xxHash/build/cmake', ['-DXXHASH_BUILD_XXHSUM=OFF'])
run([CMAKE, '--install', xx])
ft = cmake_build('freetype', BUILD / 'freetype', [
    '-DFT_DISABLE_BZIP2=ON', '-DFT_DISABLE_PNG=ON', '-DFT_DISABLE_HARFBUZZ=ON',
    '-DFT_DISABLE_BROTLI=ON', '-DFT_DISABLE_HVF=ON'])
run([CMAKE, '--install', ft])

# macOS supplies zlib in the SDK, but not a zlib.pc for pkgconf.
pc = PREFIX / 'lib/pkgconfig/zlib.pc'
pc.write_text('Name: zlib\nDescription: macOS SDK zlib\nVersion: 1.2.13\nLibs: -lz\nCflags:\n')
cre = cmake_build('crengine', BUILD / 'crengine', [
    '-DAUTO=OFF', '-DFREETYPE=ON', '-DZLIB=ON', '-DPKG_CONFIG_EXECUTABLE=' + str(PREFIX / 'bin/pkgconf')])
print('CRengine built:', cre, flush=True)
run(['clang++', '-std=c++17', '-O2', '-I' + str(cre),
     '-I' + str(BUILD / 'crengine/crengine/include'), ROOT / 'tools/crengine-probe.cpp',
     cre / 'libcrengine.a', PREFIX / 'lib/libfreetype.a', PREFIX / 'lib/libxxhash.a',
     '-lz', '-o', RUNTIME / 'crengine-probe'])
print('Position probe ready:', RUNTIME / 'crengine-probe', flush=True)
