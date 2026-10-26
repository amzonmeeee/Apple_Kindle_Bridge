# Runtime setup

## Library commands

Use macOS and Python 3.9 or later.
The library commands use the Python standard library.
They do not need Node or CRengine.

## Position conversion

The conversion tools need Node, jsdom, a C++ compiler, CMake, and the CRengine dependencies.
The tested environment uses Apple Silicon and Node 24.
The runtime files are local and do not form part of the Git repository.

### Install the Node dependency

1. Create the runtime directory:

   ```sh
   mkdir -p .runtime/node
   ```

2. Copy the dependency files:

   ```sh
   cp third_party/positions/package.json third_party/positions/package-lock.json .runtime/node/
   ```

3. Install the locked dependencies:

   ```sh
   npm ci --prefix .runtime/node --no-audit --no-fund
   ```

### Prepare the engine sources

Use the source URLs in [runtime-manifest.json](../third_party/positions/runtime-manifest.json).
Download the CRengine, pkgconf, xxHash, and FreeType archives.
Compare each archive with its recorded SHA-256 value.
Extract the verified archives into `.runtime/src/`.
Keep the archive directory names.

The build script expects these directory name prefixes:

```text
.runtime/src/crengine-*
.runtime/src/pkgconf-*
.runtime/src/xxHash-*
.runtime/src/freetype-*
```

Install CMake in the local runtime directory:

```sh
python3 -m pip install --target .runtime/python cmake==3.31.6
```

### Build the engine probe

Use the Apple command-line developer tools or Xcode for the C++ compiler.
Run the build script:

```sh
python3 tools/build-engine.py
```

The script builds in a separate temporary directory.
It writes the final executable to `.runtime/crengine-probe`.
It does not install files in system directories.

The build enables FreeType and zlib.
It disables optional engine features.
It supports EPUB import and position checks, not complete reader operation.

## Private files

Git excludes `state/`, `.runtime/`, browser sessions, and login data.
Do not add library snapshots or book files to a commit.
Reports can contain book titles, identifiers, and local paths.
