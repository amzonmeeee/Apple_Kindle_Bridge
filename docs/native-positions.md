# Native reading positions

Use the existing Mac Kindle app and Apple Books with one downloaded KFX cloud book
and its Apple EPUB. This is a manual transfer. Select the source direction each time.
There is no background service and no automatic winner when both readers move.

## Commands

Install the optional [native runtime](native-highlights.md#local-runtime).
The position conversion tools in [setup](setup.md) are also required.
Prepare a report first:

```sh
python3 -m apple_kindle_bridge native-position \
  --asset-id APPLE_ASSET_ID --kindle-book-id KINDLE_BOOK_ID \
  --to kindle --output state/position-plan.json
```

Add `--apply` and use a new output name to write. Select `--to apple` for the reverse
direction. Each write closes the target app, checks for changed positions, saves a
SQLite backup, and reopens the book. Backups default to `state/native-backups/`.

The native reader supplies KFX positions. The existing clippyconvert passage maps
connect them to EPUB text. Foliate, Readest, and CRengine verify the resulting CFI.
A repeated passage, a missing text character, or a different position space causes
a refusal. No approximate percentage is used as a resume position.

For a verified KOReader conversion report, write the Apple side directly:

```sh
python3 -m apple_kindle_bridge apple-position state/verified-reader-position.json \
  --asset-id APPLE_ASSET_ID --expected-cfi 'CURRENT_APPLE_CFI' \
  --apply --output state/apple-position-receipt.json
```

The expected CFI must still match the live bookmark. The source report must match
the target EPUB fingerprint, source coordinates, and engine version.

## Scope and limits

- Kindle writes are gated to the tested Mac app version, 7.70.1.
- Only downloaded cloud KFX books are accepted by the native position command.
- Apple needs one active CFI reading bookmark without archived page data.
- Apple current and furthest fractions are not copied from Kindle or used to
  override the requested CFI. The app can update its display percentage on reopen.
- Kindle's saved position can move to another character on the displayed page.
  A reader does not necessarily store the first visible character.
- `write_performed` reports a local database write. It does not prove that an app
  displayed the location or that a cloud service sent it to another device.
- The pilot user confirmed both Mac apps reopened at the requested third chapter.
- The pilot user also confirmed the backward transfer to the first chapter on
  both Mac apps and the Apple mobile devices. Reverse transfer used the position
  actually saved by Kindle. Three within-paragraph offsets passed conversion
  round trips, and equivalent page-range and point CFIs caused no repeat write.
- Physical Kindle results apply to the tested device and firmware only.
  See [device results](#device-results).
- The existing KOReader progress-service command is still read-only. Native Mac
  position writes do not implement KOReader device writes.

## Device acceptance

Use the original test book before trying a personal book. Confirm a forward move,
a backward move, close and reopen, and reconnect after an offline session. Check
that the device returns to the intended passage and that highlights and notes
remain present. Keep the distinction between current position and furthest progress.

A failed device check must remain a recorded limitation. Do not advance a common
synchronization baseline merely because a local write or conversion succeeded.

## Device results

Tested on 2026-11-03 with a stock Kindle Paperwhite 5 (firmware 5.19.2) and
Mac Kindle 7.70.1. The EPUBs were sent through Send to Kindle.

- Highlights, colors, and notes written on the Mac appeared on the device.
- Forward: a device position reached Mac Kindle as a "Go to most recent page"
  prompt. The bridge then wrote it to Apple Books.
- Backward: an Apple position written to Mac Kindle reached the device as
  "From page 3 to 1". It landed correctly and stayed after reopening.
- Offline: the device kept its offline position after reconnecting. It showed
  "From page 61 to 171" for the newer Mac position and moved only after the user
  accepted. The cloud never replaced the device position without the prompt.
- A six-page test book showed no prompt for a small offline difference. Use a
  longer book for conflict checks.
- Mac Kindle stores the start of the displayed page when it reopens a book, so
  a written position can shift slightly within that page.
- Let each side finish syncing before the next step.
- Apple Books keeps imported EPUBs as directory bundles. Zip the bundle with
  `mimetype` first and stored before using Send to Kindle.

Full private evidence: `state/kpw5-acceptance-20261103.json`.

## Pilot cleanup

The temporary tools were removed after the pilot. The temporary Kindle app and
its newly created main container were moved to Trash. The test book remains in
Apple Books and the Amazon cloud. Private receipts, backups, and the test EPUB
remain under `state/`, outside Git.

Native commands need the app and optional runtime installed again before use.
The old runtime configuration was archived with the private evidence because
its temporary paths no longer exist. Position conversion tools remain available.
