# Reused position conversion

The upstream files below are unmodified. The local Node adapter strips TypeScript types and replaces module imports at runtime. Apple offset-only ranges are normalized by the Python adapter after validating their assertions against the source EPUB.

| File | Source | Upstream Git blob SHA | License |
| --- | --- | --- | --- |
| `xcfi.ts` | [Readest](https://github.com/readest/readest/blob/main/apps/readest-app/src/utils/xcfi.ts) | `576e7269b39a5facdddb0f43ec8c07c533c7c29c` | AGPL-3.0, see `LICENSE.readest` |
| `epubcfi.mjs` | [Readest's Foliate fork](https://github.com/readest/foliate-js/blob/4735e67932578d4f3510276412a1a196d482d66b/epubcfi.js) | `c95b13be5d76fbc9990195c6d47905d00bbe4b43` | MIT, see `LICENSE.foliate` |

The converter runs as a local developer tool. Preserve these notices and comply with the upstream licenses if distributing it or offering it as a service. There is no new independent CFI/XPointer conversion algorithm in this project.

The independent probe links the real [KOReader CRengine](https://github.com/koreader/crengine/tree/f335f7a97e240f505bb8a0dfb721fcb7912a7824), whose source and license remain in `.runtime/src/`. The probe imports EPUBs and resolves positions without rendering pages. Its minimal build enables FreeType and zlib and disables optional format/rendering libraries; this is not a complete KOReader build.
