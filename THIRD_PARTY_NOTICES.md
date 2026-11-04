# Third-party notices

Apple Kindle Bridge is licensed under the GNU Affero General Public License,
version 3 ([LICENSE](LICENSE)). It includes or downloads the components below.

## Included in the source and the app bundle

| Component | Use | License | Source |
|---|---|---|---|
| Readest `xcfi.ts` | CFI to XPointer conversion | AGPL-3.0 ([text](third_party/positions/LICENSE.readest)) | https://github.com/readest/readest |
| Foliate `epubcfi.mjs` | EPUB CFI parsing | MIT ([text](third_party/positions/LICENSE.foliate)) | https://github.com/johnfactotum/foliate-js |
| CRengine (in `crengine-probe`) | EPUB position verification | GPL-2.0-or-later | https://github.com/koreader/crengine at `f335f7a9` |
| FreeType (in `crengine-probe`) | Font engine for CRengine | FreeType License (FTL) | https://gitlab.freedesktop.org/freetype/freetype |
| xxHash (in `crengine-probe`) | Hashing for CRengine | BSD-2-Clause | https://github.com/Cyan4973/xxHash |

`crengine-probe` is built from the pinned sources in
[runtime-manifest.json](third_party/positions/runtime-manifest.json) by
`tools/fetch-engine-sources.py` and `tools/build-engine.py`, using
`tools/crengine-probe.cpp`. Those files are the corresponding source.

## Downloaded by the app on first launch

These are fetched from their publishers into the user's Application Support
folder and are not redistributed by this project.

| Component | License |
|---|---|
| Python (python-build-standalone) | PSF License and bundled licenses |
| lxml | BSD-3-Clause |
| Node.js | MIT and bundled licenses |
| jsdom (locked by `third_party/positions/package-lock.json`) | MIT |
| Calibre | GPL-3.0 |
| KFX Input plugin | GPL-3.0 |
| clippyconvert | No license file at the pinned revision; used unmodified from its public repository |

Amazon, Kindle, Apple, and Apple Books are trademarks of their owners. This
project is not affiliated with them.
