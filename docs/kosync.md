# Read KOReader progress

The adapter uses the existing KOReader progress service.
It makes one authenticated GET request.
It does not create an account, start a production server, or upload a position.

## Prepare the book

For an expanded Apple EPUB, prepare a private ZIP copy:

```sh
python3 -m apple_kindle_bridge kosync-document /path/to/book.epub \
  --output state/kosync-document.json
```

The report gives the prepared file path and its KOReader document key.
Use that exact file on KOReader.
For an EPUB already on KOReader, use the exact reader file instead.

Select **Binary** as the document matching method in KOReader.
The adapter does not use filename matching.
It compares the complete content fingerprint before the network request.
The service document key uses KOReader's partial-MD5 method.
This key is not a complete content fingerprint.

## Configure the connection

Set these environment variables in the process that runs the command:

| Variable | Value |
| --- | --- |
| `KOSYNC_SERVER` | The existing service URL |
| `KOSYNC_USERNAME` | The KOReader account name |
| `KOSYNC_USERKEY` | The saved KOReader authentication key |

Use the authentication key, not the plain password.
Do not put credentials in the server URL or command arguments.
The adapter does not save credentials in reports.

Use HTTPS for a remote service.
HTTP is permitted only for a local test server.
The adapter rejects redirects.

## Read a position

Supply the DOM version used by the KOReader document.
The service does not report this version.
The adapter compares the supplied version with the local verification engine.

```sh
python3 -m apple_kindle_bridge kosync-pull /path/to/apple-book.epub \
  --reader-file /path/to/exact-reader-file.epub \
  --dom-version 20260812 \
  --output state/koreader.json
```

Use `--server` to override `KOSYNC_SERVER` when necessary.
The version above is the version of the current local engine.
Do not use that value for a reader with a different DOM version.

The command converts the remote XPointer with the existing conversion adapter.
CRengine must verify the source position before the report can enter a synchronization plan.
The report records the remote percentage but does not use it to select a position.

Use the report with the [synchronization commands](usage.md#prepare-a-synchronization-plan).
A successful read does not show that a physical Kindle resumed at the position.

## Verification scope

The local HTTP test checks the request path, authentication headers, and API version header.
It also checks redirect rejection and rejects PDF page numbers as EPUB positions.
No external account or physical Kindle was used in these tests.
One local API response also passed the real CRengine check and the common-position comparison.

Protocol sources:

- [API methods](https://github.com/koreader/koreader/blob/master/plugins/kosync.koplugin/api.json)
- [Client headers](https://github.com/koreader/koreader/blob/master/plugins/kosync.koplugin/KOSyncClient.lua)
- [Binary document key](https://github.com/koreader/koreader/blob/master/frontend/util.lua)
