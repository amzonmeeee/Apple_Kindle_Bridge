# Work plan

## Highlights and notes

- [ ] Transfer highlights between Apple Books and Kindle. Use
  [clippyconvert](https://github.com/seanmatheny/clippyconvert) as the reference.
- [x] Export Apple Books highlights, notes, source IDs, and deleted records.
  Use `highlights-export`; see [the command guide](docs/highlights.md).
- [ ] Reuse an existing passage matcher and MOBI/KFX position reader.
  Check the upstream license before adding source files.
- [ ] Keep explicit book links and transfer IDs. Prevent duplicate transfers.
  Do not infer the source app from a missing chapter title.
- [ ] Prepare a transfer preview for one book. Report ambiguous text matches.
- [ ] Test the Kindle app `local_edit` route with a backup and a read-back check.
  Confirm that the highlight reaches the target device.
- [ ] Test the reverse transfer and Apple Books iCloud propagation.
  Define a separate deletion policy before transferring deletions.

## Reading positions

- [ ] Connect the verified synchronization plan to the existing KOReader service.
  Keep original reader observations separate from converted positions.
- [ ] Test open, read, close, and reopen on a supported Kindle with KOReader.
- [ ] Study [kindle.koplugin](https://github.com/kaikozlov/kindle.koplugin)
  for native Kindle position maps. Its device route requires a jailbreak.
- [ ] Verify Apple Books position writes and propagation to iPhone and iPad.
  A local database change is not proof of iCloud synchronization.

See [reuse decisions](docs/reuse.md) for the repository review.
