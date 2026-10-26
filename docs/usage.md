# Commands

Run commands from the project directory.
Use a new output name for each report.
The commands do not replace existing output files.

## Inspect the Apple Books library

```sh
python3 -m apple_kindle_bridge inspect
python3 -m apple_kindle_bridge export --output state/before.json
```

After a reading session, export a second report.
Compare the two reports.

```sh
python3 -m apple_kindle_bridge export --output state/after.json
python3 -m apple_kindle_bridge diff state/before.json state/after.json
```

To use database copies, specify their paths:

```sh
python3 -m apple_kindle_bridge inspect \
  --library-db /path/to/library.sqlite \
  --annotations-db /path/to/annotations.sqlite
```

An explicit library path does not select the annotation database on the Mac.
If automatic discovery finds multiple databases, specify the required paths.

## Check EPUB positions

```sh
python3 -m apple_kindle_bridge positions state/after.json \
  --output state/positions.json
```

This command checks candidate positions against local EPUB files.
It does not establish that a reader will resume at those positions.

## Convert a position

Complete the [runtime setup](setup.md) first.
Use an EPUB CFI from an Apple Books report:

```sh
python3 -m apple_kindle_bridge to-koreader /path/to/book.epub \
  'epubcfi(...)' --output state/apple.json
```

Use an XPointer from KOReader for the reverse conversion:

```sh
python3 -m apple_kindle_bridge from-koreader /path/to/book.epub \
  '/body/DocFragment[3]/body/p[12]/text().222' \
  --end-xpointer '/body/DocFragment[3]/body/p[12]/text().223' \
  --output state/koreader.json
```

The values above are examples.
Use positions from the specified EPUB.
Omit `--end-xpointer` for a single point.

Conversion returns exit code 0 after successful verification.
It returns exit code 2 when it cannot verify the position.
The report gives the cause.
Neither command changes reader settings.

To read a position from the existing KOReader service, use the [connection instructions](kosync.md).

## Prepare a synchronization plan

A baseline records a position common to both input reports.
Create a baseline only when both reports identify the same source position:

```sh
python3 -m apple_kindle_bridge sync-baseline \
  state/apple.json state/koreader.json --output state/common.json
```

Get new position reports before each comparison.
Compare them with the baseline:

```sh
python3 -m apple_kindle_bridge sync-plan \
  state/apple-new.json state/koreader-new.json \
  --baseline state/common.json --output state/plan.json
```

| Condition | Result |
| --- | --- |
| Both current positions are equal | No change |
| Only the Apple position changed | Apple to KOReader |
| Only the KOReader position changed | KOReader to Apple |
| Both positions changed and differ | Conflict |
| Positions differ without a baseline | Initial source selection required |

Backward reading is a valid position change.
The plan does not select the larger reading percentage.
It does not use device time to resolve a conflict.

To select the source for an initial plan, use `--prefer`:

```sh
python3 -m apple_kindle_bridge sync-plan \
  state/apple.json state/koreader.json \
  --prefer apple --output state/initial-plan.json
```

To resolve a later conflict, supply both `--baseline` and `--prefer`.
The source can be `apple` or `koreader`.

## Check a plan before use

Get fresh reports from both sides.
Check them against the plan:

```sh
python3 -m apple_kindle_bridge sync-check \
  state/apple-new.json state/koreader-new.json \
  --plan state/plan.json --output state/check.json
```

The check rejects changed positions, book identity, or input evidence.
It checks the supplied files; it does not read a Kindle directly.

A plan is not a synchronization receipt.
These commands do not write reader data or advance the baseline.
Historical input reports produce an offline simulation only.

| Exit code | Meaning |
| --- | --- |
| `0` | The operation completed without an unresolved choice |
| `1` | An input, file, or schema error stopped the operation |
| `2` | Conversion failed, or a plan needs source selection |
