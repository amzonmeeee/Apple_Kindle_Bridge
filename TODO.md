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

## Next: physical Kindle acceptance

- [ ] Confirm the model and firmware, then test the existing cloud book on the device.
- [ ] Verify highlights, colors, and notes on the physical Kindle.
- [ ] Verify forward and backward positions through Whispersync, then close and reopen.
- [ ] Verify offline reading and reconnect. Record how competing device changes behave.

These are hardware acceptance gates, not a promise of stock Kindle compatibility.
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
