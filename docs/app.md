# Mac app

`Apple Kindle Bridge.app` is a SwiftUI front end for the Python bridge.
It is for personal use and is signed ad hoc.

## Build

```sh
./app/build.sh            # writes ~/Applications/Apple Kindle Bridge.app
```

The build needs the Swift compiler and the CRengine probe in `.runtime/`
([setup](setup.md)). It also needs the private Kindle edit capture from
`state/native-pilot-evidence/ksdk_capture.json`, or a path in `AKB_CAPTURE`.
The app bundle holds only the bridge source, the probe, and the capture.

## First launch

The app downloads its tools into
`~/Library/Application Support/Apple Kindle Bridge/runtime`. Every download is
pinned to a version and checksum in `apple_kindle_bridge/runtime_install.py`:
Python 3.12.16, lxml 6.1.3, Node 24.22.1 with the locked jsdom, Calibre 9.17.0,
KFX Input 2.34.2, and clippyconvert at the reviewed commit. The runtime takes
about 1.4 GB, mostly Calibre. Settings → Remove deletes the whole folder.

Onboarding checks the tools, Full Disk Access, Kindle for Mac, and the Kindle
sign-in. Grant Full Disk Access to the app itself. An ad hoc signature changes
on each rebuild, so macOS can ask for access again after a rebuild.

## Sync

On launch the app pairs books and lists their state. Books that need a sync
come first. Every difference is selected by default and can be cleared.

- Pairs come from uploads made by the app, or from an exact title match that is
  unique on both sides.
- A baseline in `data/baselines/` stores both sides after each sync. A side that
  differs from it has changed. Without a baseline, the newer side is the default.
- Positions within 1,500 Kindle positions count as the same page.
- Highlight additions go both ways. Apple Books edits and deletions are written.
  Kindle edits and deletions are listed but need a capture of the Kindle edit
  format first; until then they are not selectable.
- Each write quits the target app, backs up its database to `backups/`, and
  reopens it.

The exact Kindle version gate was removed. The writers check the database
columns they use. An untested Kindle version shows a warning in onboarding.

## Import

- Apple Books to Kindle: the app zips Apple's EPUB folders and hands them to the
  system Send to Kindle share service. Confirm the Send to Kindle window. Then
  download the book in Kindle for Mac; the app pairs it.
- Kindle to Apple Books: downloaded personal documents are converted from KFX to
  EPUB with Calibre and KFX Input, then opened in Apple Books.
- Store purchases with DRM on either side are listed as unavailable.
- Kindle for Mac lists only downloaded books.
