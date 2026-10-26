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

## Next usable result

- [ ] Complete reading-position transfer on the selected reader route.
  Confirm the position after the book closes and opens again.
  Keep deliberate backward reading and identify conflicting changes.
- [ ] Add Kindle-to-Apple note import. Existing Apple notes must remain intact.
- [ ] Verify highlights and reading positions on a physical Kindle.
  Mac app acceptance does not establish device behavior.
- [ ] Remove the temporary native test app and tools after the native pilot ends.

Native imports reuse [clippyconvert](https://github.com/seanmatheny/clippyconvert).
Do not add automatic deletion or conflict resolution until their rules are defined.

## Work rule

Use existing parsers and converters.
Add code only when it closes a gap in the next usable result.
Do not add another preview format, service, or reader integration as a substitute
for testing a real import. Run focused checks, then continue to that import.

See [reuse decisions](docs/reuse.md) and [highlight commands](docs/highlights.md).
