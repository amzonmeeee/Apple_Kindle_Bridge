# Work plan

## Scope

The main task is reading-position transfer between Apple Books and Kindle.
Highlight and note transfer is also in scope.
A feature is complete when the target app can use the transferred data.
JSON exports, conversion checks, and previews are supporting tools.
They are not completed synchronization features.

## Available now

- [x] Read Apple Books library data, current-position candidates, and highlights.
- [x] Check EPUB position conversion with Readest, Foliate, and CRengine.
- [x] Prepare position plans and one-book KOReader highlight previews.
- [x] Transfer a highlight and note from Apple Books to the Mac Kindle cloud book.
  Confirm display after upload and detect the existing import on a repeat run.
- [x] Transfer Kindle highlights to Apple Books. Confirm iCloud propagation.
- [x] Preserve shared highlight colors. Confirm pink on Mac, iPhone, and iPad.
- [x] Import a new Kindle-only note into Apple Books. Preserve existing note conflicts.
- [x] Transfer native reading positions between the Mac apps.
  Confirm forward and backward resume after reopening the original test book.
  Confirm the backward Apple position on the user's mobile devices.
- [x] Remove temporary tools. Move the test app and its new main container to Trash.

## Physical Kindle acceptance (2026-11-03)

Device: Kindle Paperwhite 5 8GB, firmware 5.19.2, stock (no jailbreak, no KOReader).

- [x] Confirm the model and firmware, then test a cloud book on the device.
- [x] Verify highlights, colors, and notes on the physical Kindle.
- [x] Verify forward and backward positions through Whispersync, then close and reopen.
- [x] Verify offline reading and reconnect. Record how competing device changes behave.
  Tested on a long book; see [device results](docs/native-positions.md#device-results).

## Mac app

See [Mac app](docs/app.md).

- [x] Relocatable runtime with pinned first-run downloads.
- [x] Library pairing, status with baselines, apply, and imports.
- [x] SwiftUI app with onboarding, sync list, library, and settings.
- [x] Test onboarding, sync, and both imports in the app (2026-11-04).
  Mock books in both directions arrived with highlights, colors, and notes.
- [x] Capture the Kindle edit and delete format to enable those writes.
- [ ] Try one personal book with existing highlights before wider use.

These results cover one device, firmware, and Mac app version.
The current implementation is a manual, one-book native Mac transfer.
KOReader device writes and unattended conflict resolution are not implemented.
See [supported position scope](docs/native-positions.md).

Native imports reuse [clippyconvert](https://github.com/seanmatheny/clippyconvert).
Do not add automatic deletion or conflict resolution until their rules are defined.

## Work rule

Use existing parsers and converters.
Add code only when it closes a gap in the next usable result.
Do not add another preview format, service, or reader integration as a substitute
for testing a real import. Run focused checks, then continue to that import.

See [reuse decisions](docs/reuse.md) and [highlight commands](docs/highlights.md).
