# Highlights

For actual app transfers, use [native highlight transfer](native-highlights.md).
The commands below export data or prepare a KOReader preview.

## Export

Export Apple Books highlights and attached notes:

```sh
python3 -m apple_kindle_bridge highlights-export --output state/highlights.json
```

Use `--asset-id BOOK_ID` to select one book.
For database copies, supply both `--library-db PATH` and `--annotations-db PATH`.

The command reads type 2 annotations from a database snapshot.
It keeps the UUID, book ID, source CFI, text, note, style, and dates.
It also keeps deleted records and reports missing or duplicate source IDs.
Reading-position bookmarks are excluded.

The report contains private text and notes.
The output file has owner-only access. Existing files are not replaced.
The terminal shows counts, not passages or notes.
Keep exports in the Git-excluded `state/` directory.

This command does not match a Kindle book or transfer annotations.
It does not verify the source CFI or the target position.
Deleted records do not cause target deletions.
A missing chapter title does not prove which app created a highlight.

See the [reuse decisions](reuse.md) and [remaining work](../TODO.md).

## Preview one book for KOReader

Install the [position conversion tools](setup.md) first.
Use the Apple Books EPUB and the exact EPUB file intended for KOReader.
Both files must have the same content.
An expanded Apple Books EPUB directory is also supported.

```sh
python3 -m apple_kindle_bridge highlights-plan state/highlights.json \
  /path/to/apple-book.epub --asset-id BOOK_ID \
  --reader-file /path/to/reader-book.epub --output state/highlight-plan.json
```

Use `kosync-document` to prepare a ZIP copy if you do not yet have a reader file.
That command reports the copy path. It does not send the file to a device.

The preview uses the source CFI to select the passage with Foliate.
The selected text must match the exported highlight exactly.
Readest converts the range. CRengine checks both endpoints.
The command does not search for another occurrence when a passage fails this check.
It rejects different EPUB content and keeps the book link explicit.

Each verified record includes the start and end XPointer, text, and note.
It keeps the source style and underline fields without a target style conversion.
A stable transfer ID identifies the source annotation and target book.
A separate revision hash detects changes to the text, note, style, or CFI.
The output remains private and does not replace an existing file.

Deleted records are skipped. Other rejected records include a reason.
Exit code `2` means the preview contains rejected records.
Exit code `1` means that the input or book check failed.

This is a KOReader preview, not a native Kindle MOBI/KFX import file.
It does not read existing target annotations or prevent duplicates on a device.
It does not write annotations, render highlights, or verify cloud synchronization.
The future importer must read target annotations and check the saved source revision.
