# Data handling and verification

## Terms

| Term | Meaning |
| --- | --- |
| CFI | An EPUB Canonical Fragment Identifier |
| XPointer | A position used by the KOReader reading engine |
| Current position | The location where the reader stopped |
| High-water mark | The furthest recorded reading progress |
| Baseline | A source position common to two verified input reports |
| Fingerprint | A SHA-256 value used to identify a private EPUB copy |

## Apple Books data

Inspection opens each SQLite database with `mode=ro` and `query_only=ON`.
It uses the SQLite backup API to create a memory snapshot.
This includes committed write-ahead log data.
Each snapshot must pass `quick_check`.
The two databases do not share one transaction time.

The tool keeps current progress and the high-water mark separate.
It preserves hidden library rows and missing file records.
It reports missing or duplicate asset identifiers.
It rejects ambiguous book comparisons.

Type 3 annotation rows are candidate reading positions.
The tool keeps their raw values, including absent CFIs and deletion flags.
It does not use the newest highlight as a reading position.

Position inspection does not export note text or highlight text.
Highlight exports and native transfer reports do contain selected text and notes.
Native transfer commands can write annotations when `--apply` is set.
They close the target app and save a database backup before a write.
See [native transfer](native-highlights.md) for the supported scope.
For `ZPLUSERDATA`, it records a hash, length, and simple `BKPageLocation` values.
It does not expand archived text context.

## Source EPUB checks

The parser supports ZIP files and expanded EPUB directories.
It checks package references, source nodes, ID assertions, and UTF-16 offsets.
It preserves both endpoints of a range.

The parser implements a limited [EPUB CFI](https://w3c.github.io/epub-specs/epub33/epubcfi/) subset.
It rejects unsupported assertions, nested indirection, and media positions.
It does not substitute a percentage or guess a nearby position.

Some Apple CFIs use `itemref.idref` as an assertion.
The parser accepts this only when the item has no XML ID and the `idref` value matches.
It records this exception in the result.
An existing but different XML ID causes failure.

Reports contain coordinates, resource hashes, and text-node hashes.
They do not contain book text.
Source resource hashes cover inspected files only, not the complete publication.

Before a file read, the tool checks known iCloud placeholder flags and local block data.
These checks do not guarantee that macOS will never download a file.
The tool rejects custom XML entities, paths outside the EPUB, and resources above its size limits.

## Conversion checks

The adapter reuses the Readest converter and its Foliate dependency.
It changes the form of Apple offset-only ranges after source validation.
It also represents text points as empty ranges for the converter.
This avoids a text-node error in the converter's point branch.
The report keeps the original CFI.

The adapter checks conversion in both directions.
It then asks the actual CRengine to resolve the XPointer.
It compares the text node, Unicode offset, and engine-exported CFI with the source.

The current conversion scope is exact text positions in one source document.
The adapter rejects unsupported positions and text changes caused by engine normalization.
The adapter creates a private, deterministic EPUB copy for engine checks.
It does not change the source EPUB.

CRengine commit: `f335f7a97e240f505bb8a0dfb721fcb7912a7824`.
DOM version: `20260812`.
The probe imports EPUB content and resolves positions without page rendering.
It is not the complete KOReader application.

## Synchronization rules

The planner requires the same EPUB fingerprint and DOM version on both sides.
It compares range starts, because a different page size can change the range end.
It does not copy percentages between reader layouts.
It preserves the high-water mark independently.

Both input reports must have successful engine verification.
Before application, a future writer must obtain fresh reports and check plan conditions.
The current planner does not perform device writes.

The [KOReader service adapter](kosync.md) supplies verified reports to this planner.
It uses the existing progress API and does not change remote records.

## Completed verification

- One iPhone-to-Mac observation confirmed forward and backward position changes.
- The backward position matched the first character in the supplied screen image.
- Current progress decreased while the high-water mark remained unchanged.
- CRengine verified two source positions and one reverse range conversion in the same EPUB.
- Focused planner tests cover backward changes, conflicts, book identity, and stale evidence.
- A local HTTP fixture connects the KOReader API adapter to the real CRengine and the baseline comparison.

These results do not establish universal compatibility with other books or firmware.
Page rendering, saved-position reopening, Apple writeback, and Kindle device behavior remain unverified.

## Existing implementations

- [Readest conversion](https://github.com/readest/readest/blob/main/apps/readest-app/src/utils/xcfi.ts): the reused CFI/XPointer converter.
- [KOReader reading state](https://github.com/koreader/koreader/blob/master/frontend/apps/reader/modules/readerrolling.lua): resumes from `last_xpointer` and exports `last_epubcfi`.
- [py-apple-books](https://github.com/vgnshiyer/py-apple-books/blob/main/py_apple_books/_api/positions.py): observations about Apple position fields.
- [Apple Books/BOOX sync](https://github.com/BearChao/apple-books-boox-sync): background for database handling; its maximum-progress merge differs from this project.
- [krdsrw](https://github.com/midrare/krdsrw): reads and writes native Kindle sidecar data.
- [kindle.koplugin](https://github.com/kaikozlov/kindle.koplugin): native Kindle/KOReader position synchronization on jailbroken devices.

Sidecar serialization alone does not prove that a stock Kindle will use a changed position.
Third-party source notices and licenses are in [the conversion directory](../third_party/positions/README.md).
