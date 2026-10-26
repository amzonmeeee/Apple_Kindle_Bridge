# Highlight export

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
