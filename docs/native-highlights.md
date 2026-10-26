# Native highlight transfer

These optional commands transfer annotations for one explicit book pair.
They use the Mac Kindle app, Apple Books, and a separate clippyconvert checkout.
For reading positions, use [native position transfer](native-positions.md).

## Verified result

The 2026-10-26 pilot used an original book, **Bridge Transfer Check**.
The user sent its EPUB through Send to Kindle and downloaded the cloud copy.
The local MOBI copy was a separate book and was not used as cloud evidence.

| Check | Result |
| --- | --- |
| Apple highlight and attached note to Kindle | Upload queue emptied; server records present; user confirmed display |
| Repeat forward import | Existing highlight and note detected; no second write |
| Kindle highlights to Apple Books | User confirmed display on Mac, iPhone, and iPad |
| Pink color correction | Existing Apple note preserved; user confirmed pink on all three Apple devices |
| New pink import through the adapted writer | Style 4 written to an isolated database copy; repeat import added no row |
| New Kindle note to Apple | Third-chapter note was absent in Apple before import; user confirmed the new note and blue highlight after reopen |
| Physical Kindle | Not tested |

The pilot used Kindle 7.70.1, Calibre 9.17.0, KFX Input 2.34.2, and lxml 6.1.3.
This is evidence for one book and these versions. It is not a compatibility claim
for all books, app versions, or Kindle devices.
The temporary app and tools were removed after the pilot; see [cleanup](native-positions.md#pilot-cleanup).

## Local runtime

Use clippyconvert revision `49dd307fe6132ccdb965c4adb948d30f2287ec34`.
The [source manifest](../third_party/clippyconvert/manifest.json) checks its files
before use. Keep this checkout separate from the bridge repository.
Install lxml for the Python interpreter that runs the bridge.
KFX books also need Calibre and the KFX Input plugin. No new book parser is used.

Create a private `.runtime/native.json` file with these paths:

```json
{
  "clippy_root": "/path/to/clippyconvert",
  "python_dependencies": "/path/to/local-python-packages",
  "calibre_debug": "/path/to/calibre.app/Contents/MacOS/calibre-debug",
  "calibre_config": "/path/to/private-calibre-config",
  "kfx_input_plugin": "/path/to/KFX Input.zip",
  "cache_dir": "/path/to/private-kfx-cache",
  "capture": "/path/to/private-ksdk-capture.json",
  "kindle_app": "/Applications/Amazon Kindle.app"
}
```

Forward writes require native edit codes and the note offset captured from the
installed Kindle version. Add that observed version as `kindle_version` in the
capture file. Do not copy codes from another installation or assume the note
offset is 6. The pilot observed offset 0 from a native highlight and note.
The upstream `books2kindle.py capture` command is interactive and asks for an
offline capture. The pilot instead observed its own test edits while online.
The bridge does not automate this setup step or change network settings.

Use a downloaded Kindle cloud book and the corresponding local Apple EPUB.
Select the Apple asset ID from `inspect` or `highlights-export`.
Use clippyconvert's `ksdk.load_kindle_books()` to obtain the canonical Kindle
`bookid`. The bridge requires an exact ID with a cloud GUID, not a title match.
No account credentials or private capture files belong in Git.

## Commands

First prepare a report. Use a new output name for every run.

```sh
python3 -m apple_kindle_bridge kindle-highlights \
  --asset-id APPLE_ASSET_ID --kindle-book-id KINDLE_BOOK_ID \
  --output state/to-kindle-plan.json

python3 -m apple_kindle_bridge apple-highlights \
  --asset-id APPLE_ASSET_ID --kindle-book-id KINDLE_BOOK_ID \
  --output state/to-apple-plan.json
```

Add `--apply` to write. Use `--annotation-uuid UUID` to select one Apple source
annotation for a forward import. Use `--kindle-annotation-id ID` to select one
Kindle highlight and its attached note for a reverse import. Backups go to `state/native-backups/` unless
`--backup-dir` selects another folder. Reports and backups can contain private data.

The tool closes the target app before a write, checks for changes, saves a
SQLite backup, and reopens the app. A forward result of `queued` means only that
the local queue write succeeded. Confirm upload and target display separately.

## Limits

- Matching requires one exact normalized passage. Ambiguous passages are refused.
- Yellow, blue, and pink retain their color. Unsupported colors are refused.
- Underline is a separate style. Its device display has not been verified.
- Both directions carry notes attached to highlights. Standalone notes are not imported.
- Reverse notes must match one highlight at the captured endpoint offset. Ambiguous attachments are refused.
- Existing Apple notes remain intact. A visible note that already existed in
  Apple Books is not evidence of reverse note transfer.
- Existing target conflicts stop the import. Color changes and note edits are
  not merged automatically. The pilot color repair was a separate scoped update.
- Deletions are not transferred. There is no background synchronization service.
- Native position writes use a separate command. Highlight imports do not move the reader.

Keep a database backup before an import. Restore it only with the app closed;
cloud synchronization can reapply records after a local restore.
