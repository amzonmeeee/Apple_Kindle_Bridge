# Reuse decisions

Review date: 2026-10-26.
The local `Apple_Kindle_Bridge_similar_repos.md` report supplied the candidates.
This review checked the sources listed below. It did not run these applications.

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
Reuse those components where suitable. Do not build another MOBI or KFX parser.
Check the upstream license before adding source files to this repository.

Keep annotation UUIDs and explicit transfer records.
The upstream export treats a chapter field as evidence of a native annotation.
That heuristic is not sufficient for this bridge to prevent transfer loops.
Fuzzy book names and repeated passages also need review before a write.

The Kindle queue is an annotation route.
It does not establish a route for writing the last reading position.
Device and cloud propagation remain untested here.

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
