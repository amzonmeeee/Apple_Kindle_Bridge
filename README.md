# Apple Kindle Bridge

Apple Kindle Bridge reads reading positions from Apple Books on macOS.
It converts EPUB positions between Apple Books and KOReader.
It also transfers highlights through the Mac Kindle app.

**This is a prototype. Physical Kindle acceptance is still required.**

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
- Native highlight transfer works in both directions on the test book.
- Both directions carry attached notes and preserve existing note conflicts.
- Pink highlights reached Apple Books on Mac, iPhone, and iPad.
- Native position commands write one book at a time. Device sync is not yet verified.

Position conversion needs the additional tools in the [setup instructions](docs/setup.md).

## Details

- [Commands and synchronization rules](docs/usage.md)
- [KOReader service connection](docs/kosync.md)
- [Data handling and verification limits](docs/design.md)
- [Native reading-position transfer](docs/native-positions.md)
- [Native highlight transfer and limits](docs/native-highlights.md)
- [Highlight export and KOReader preview](docs/highlights.md)
- [Work plan](TODO.md)
- [Third-party code and licenses](third_party/positions/README.md)

## Tests

```sh
python3 -m unittest discover -s tests -q
```
