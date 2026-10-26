# Reuse decisions

Review date: 2026-10-26.
The local `Apple_Kindle_Bridge_similar_repos.md` report supplied the candidates.
The initial review checked the sources listed below.
The later native pilot ran clippyconvert with Apple Books and the Mac Kindle app.

## Highlights

[clippyconvert](https://github.com/seanmatheny/clippyconvert) is the main reference.
Its [Apple export module](https://github.com/seanmatheny/clippyconvert/blob/main/clippy/books_export.py)
reads type 2 annotations, selected text, notes, and style fields.
The inspected file has Git blob SHA `be232e4605d789764c3616e2062064a349dfdaaa`.
Our export uses these field meanings and the existing SQLite snapshot helper.
It does not copy the upstream implementation.

Its [Kindle database module](https://github.com/seanmatheny/clippyconvert/blob/main/clippy/ksdk.py)
separates the synced `server_view` from the pending `local_edit` queue.
Its [README](https://github.com/seanmatheny/clippyconvert#reverse-direction-apple-books--kindle-app)
describes text matching, MOBI positions, and Calibre KFX Input integration.
The native adapter now reuses those components from a separate local checkout.
The tracked manifest pins its revision and source hashes. No upstream code is vendored.
No license was found at that revision. Review licensing before redistribution.

Keep annotation UUIDs and explicit transfer records.
The upstream export treats a chapter field as evidence of a native annotation.
That heuristic is not sufficient for this bridge to prevent transfer loops.
Fuzzy book names and repeated passages also need review before a write.

The inspected [passage matcher](https://github.com/seanmatheny/clippyconvert/blob/main/clippy/textsearch.py)
returns the first exact text match before trying approximate matches.
Its Git blob SHA is `057cba1a54afc941bfcb14cc2010b495fc88d4fa`.
An exact score alone does not establish a unique passage.
For the same EPUB, the current highlight preview uses the existing CFI instead.
It reuses Foliate selection ranges, Readest conversion, and CRengine endpoint checks.
No new passage matcher or MOBI/KFX parser was added.

The Kindle queue is an annotation route.
It does not establish a route for writing the last reading position.
The original test book reached the Kindle server view after import.
The user confirmed its highlight and note in the Mac Kindle app.
Reverse highlights and the pink color correction reached Apple Books on all three
Apple devices. Physical Kindle behavior remains untested.

The upstream reverse writer always selects yellow for highlights.
The adapter replaces that one expression in memory with the shared color mapping.
Yellow, blue, and pink have exact mappings. Other colors are refused.
See [native transfer evidence and limits](native-highlights.md).

## Reading positions

[kindle-reading-sync](https://github.com/abhaymettu/kindle-reading-sync/blob/main/src/bridge.js)
maps positions to the start of a text block.
The inspected file has Git blob SHA `aa056d67e421c0b5f2293d9ef4b47caf3ab66bbd`.
It deliberately omits character offsets because CRengine can change text nodes.
Keep the current Readest and CRengine checks for exact text positions.
Use the project's distinction between original and converted observations.

The supplied report identifies
[kindle.koplugin](https://github.com/kaikozlov/kindle.koplugin)
as a native Kindle position-map reference that requires a jailbreak.
Study it when selecting the device route.
Do not build a new KRDS serializer; evaluate
[krdsrw](https://github.com/midrare/krdsrw) if that route needs one.

The report also describes Apple Books to BOOX percentage synchronization.
Its maximum-progress rule does not preserve deliberate backward reading.
Keep the existing common-baseline comparison.
