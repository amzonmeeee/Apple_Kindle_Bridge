# Apple Kindle Bridge

Apple Kindle Bridge reads reading positions from Apple Books on macOS.
It converts EPUB positions between Apple Books and KOReader.
It also prepares synchronization plans.

**The tool does not yet write positions to Apple Books or a Kindle.**

## Start

Use macOS and Python 3.9 or later.
Run these commands from the project directory:

```sh
python3 -m apple_kindle_bridge inspect
python3 -m apple_kindle_bridge export --output state/books.json
python3 -m apple_kindle_bridge positions state/books.json --output state/positions.json
```

The tool saves reports in `state/`.
It does not replace existing reports.
Reports can contain private library data.
Git excludes this directory.

## Status

- Library inspection uses read-only database access.
- Position conversion uses Readest, Foliate, and the actual KOReader CRengine.
- The tool can read the existing KOReader progress service.
- Synchronization plans keep backward reading changes and identify conflicts.
- Kindle transfer and saved-position tests need further work.

Position conversion needs the additional tools in the [setup instructions](docs/setup.md).

## Details

- [Commands and synchronization rules](docs/usage.md)
- [KOReader service connection](docs/kosync.md)
- [Data handling and verification limits](docs/design.md)
- [Highlight export](docs/highlights.md)
- [Work plan](TODO.md)
- [Third-party code and licenses](third_party/positions/README.md)

## Tests

```sh
python3 -m unittest discover -s tests -q
```
