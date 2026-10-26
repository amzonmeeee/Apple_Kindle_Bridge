# Apple Kindle Bridge

目前可唯讀檢查 macOS Apple Books、匯出可比較的 JSON 快照，並把 EPUB CFI 位置候選對照到本機 EPUB 的原始 XML 節點。
另有實驗性的 CFI ↔ KOReader XPointer 轉換，重用 Readest／Foliate 並以實際 CRengine 核對；尚未實作 Kindle 傳輸、資料庫寫回或跨平台同步。
Apple Books 的原生 iCloud 同步與本橋接程式能否寫回進度是不同的驗證項目。

書庫檢查及 CFI 來源解析需要 Python 3.9 或以上，僅使用標準函式庫。KOReader 轉換另外使用隔離在 `.runtime/` 的 Node／jsdom 和 CRengine。

```sh
python3 -m apple_kindle_bridge inspect
python3 -m apple_kindle_bridge export --output state/apple-books-before.json
python3 -m apple_kindle_bridge export --output state/apple-books-after.json
python3 -m apple_kindle_bridge diff state/apple-books-before.json state/apple-books-after.json
python3 -m apple_kindle_bridge positions state/apple-books-before.json --output state/positions-before.json
```

同名輸出檔不會被覆寫。`state/` 已加入 `.gitignore`；快照包含私人書庫資料及本機路徑。

可以指定資料庫以使用測試副本：

```sh
python3 -m apple_kindle_bridge inspect --library-db /path/to/library.sqlite --annotations-db /path/to/annotations.sqlite
```

明確指定書庫時，只讀取明確指定的註解資料庫，不會混入另一份真實書庫的註解。
自動發現多個資料庫時，程式會要求明確選擇，不自行猜測最新版本。

## 讀取與資料含義

- 來源 SQLite 以 `mode=ro`、`query_only=ON` 開啟，再透過 SQLite backup API 取得記憶體快照。包含已提交的 WAL 資料，不直接複製主檔或使用 `immutable=1`。
- 每份資料庫分別取得一致性快照；書庫及註解兩個資料庫之間不保證同一交易時間點。
- 保留 `ZREADINGPROGRESS` 與 `ZBOOKHIGHWATERMARKPROGRESS` 的差別。向前翻閱不會被「取最大進度」策略覆蓋。
- EPUB CFI 等註解位置只列為候選，保留原始類型及刪除標記；不宣稱它們就是最後續讀位置。
- 參照 `py-apple-books` 的實機觀察，另外保留全部 type 3 自動書籤候選，包括 CFI 為空的紀錄、原始 fraction 欄位及頁面／spine 資料。這些含義仍需在此書庫用正常閱讀操作驗證。
- SQLite 快照須通過 `quick_check`；每份來源各自記錄擷取起訖時間。
- 保留全部書庫列，包括隱藏或檔案未在本機出現的紀錄。重複／缺失 asset ID 會明確列出，差異比較會拒絕模糊配對。
- 檔案路徑存在不代表已完整下載、可讀或沒有 DRM。`inspect`／`export` 不讀取正文；`positions` 會在本機讀取解析所需的 EPUB 資源，不傳送書籍內容。
- 未匯出筆記或標註的正文。
- `ZPLUSERDATA` 只匯出雜湊、長度及簡單 `BKPageLocation` 數值；不展開可能含前後文的 NSKeyedArchiver 內容。

## EPUB 位置解析

`positions` 接收已保存的書庫快照，只處理其中未刪除的 type 3 候選，不自行挑選最新一筆作為續讀真值。
支援 ZIP EPUB 和 Apple Books 展開的 EPUB 目錄，核對 OPF spine、manifest、XHTML 節點、ID assertion 和 UTF-16 偏移；範圍保留兩個端點。
結果只輸出座標、被讀取資源的 SHA-256 及文字節點的長度／雜湊，不輸出正文。這些資源雜湊並非完整書籍指紋。

這是 [EPUB CFI 規範](https://w3c.github.io/epub-specs/epub33/epubcfi/) 的有限子集：不支援的 text assertion、多重 indirection 和媒體位置會明確失敗，不做百分比替代或模糊修復。
Apple 候選偶爾以 `itemref.idref` 作 assertion；只有該 itemref 沒有 XML ID 且 idref 完全吻合才接受，並輸出相容性註記。有 XML ID 卻不吻合時停止。

讀取前檢查已知 iCloud placeholder 旗標及檔案區塊資訊，避免主動讀取明顯未下載的檔案；這不是作業系統層級的「永不下載」保證。XML 自訂 entity、資源越界路徑及過大的資源會被拒絕。

來源解析已在本機書庫驗證；私人快照及 EPUB 不包含在 repository。成功解析來源座標不等於另一個閱讀器已能在該處續讀。

## Kindle 路線的證據與限制

| 路線 | 已查證的實作 | 本專案尚未驗證 |
| --- | --- | --- |
| KOReader | [`readerrolling.lua`](https://github.com/koreader/koreader/blob/master/frontend/apps/reader/modules/readerrolling.lua) 從 `last_xpointer` 續讀，另存 `last_epubcfi`。本專案已重用 Readest 轉換器，並以實際 CRengine 驗證一本 EPUB 的兩個位置及其中一個位置的反向轉換。 | 完整 KOReader 排版、儲存設定後重開續讀、Kindle 上的實際操作。尚未執行完整 emulator 或 Readest 的 Lua oracle。 |
| 原生 Kindle | [`krdsrw`](https://github.com/midrare/krdsrw) 可讀寫 sidecar 格式；[`kindle.koplugin`](https://github.com/kaikozlov/kindle.koplugin) 實作原生閱讀器與 KOReader 的精確位置同步，其 README 明定需要越獄 Kindle。 | 沒有實測未越獄 Kindle 是否接受經 USB 修改的 sidecar，也尚未在本專案執行 sidecar round-trip。 |

不把「可序列化檔案」視為「原生閱讀器會採用」，也不把 `last_epubcfi` 當作 KOReader 已支援的續讀輸入。
先保留兩條路線，待實作結果再選擇。現有驗證使用指定 CRengine commit 和 DOM 版本，不自行推算 XPointer 結構。

## 可執行的 KOReader 位置轉換

```sh
python3 -m apple_kindle_bridge to-koreader /path/to/book.epub 'epubcfi(...)' --output state/to-koreader.json
python3 -m apple_kindle_bridge from-koreader /path/to/book.epub '/body/DocFragment[3]/body/p[12]/text().222' --end-xpointer '/body/DocFragment[3]/body/p[12]/text().223' --output state/from-koreader.json
```

兩個指令都只輸出報告，不寫入閱讀器設定。驗證成功才回傳 exit code 0；無法確認的位置輸出原因並回傳 2。只接受同一份 EPUB 的精確文字節點位置；元素位置、跨文件範圍、side bias 或引擎文字正規化造成的差異暫不自動修復。

流程為：來源 CFI 嚴格驗證 → 重用 Readest 轉換 → 反轉換核對來源 → 真實 CRengine 解析 XPointer → 比對完整文字節點、Unicode 偏移及引擎匯出的 CFI。Apple 的 offset-only range 會先改寫成轉換器接受的等價表示，原始 CFI 始終保留。

本機已核對同一 EPUB 的兩個 Apple Books 位置，並將其中一個範圍轉回相同來源節點與偏移；錯誤的來源 ID assertion 會在轉換前被拒絕。原始驗收報告留在已忽略的 `state/`。

引擎固定為 `koreader/crengine@f335f7a97e240f505bb8a0dfb721fcb7912a7824`，DOM 版本 `20260812`；以 Apple Silicon 原生編譯執行。這是無視窗的 EPUB 匯入及定位探針，**沒有執行頁面排版，也不代表 Kindle／KOReader 重開續讀已驗證**。

`.runtime/` 不隨 repository 發布；首次使用位置轉換需要另外準備依賴。`tools/build-engine.py` 使用 `.runtime/src/` 中已下載的固定來源，在獨立暫存目錄編譯，產出 `.runtime/crengine-probe`；不安裝到系統。來源、版本、SHA-256 和授權記錄見 `third_party/positions/`。Node 依賴的 lockfile 亦保存在該處；轉換器本身未修改。

此輪驗收到此為止，不以更多 smoke／regression 測試取代下一階段的實際功能。仍待實作的部分是同步協調、傳輸及寫回；後續實機驗收則包含排版、關書重開、斷線重連。

## 裝置驗證範圍

已觀察到一次 iPhone → Mac 的前進與倒退同步：同一筆 type 3 自動書籤會移動，目前進度可以下降而最遠進度不變，倒退後的 CFI 對上 iPhone 畫面首字。這是一個 EPUB 的觀察，沒有實測重新開書續讀、Apple 資料庫寫回或 Kindle 實機。

後續需分別驗證雙方修改時的衝突處理、關書重開、斷線重連和 Apple 裝置之間的寫回傳播。

## 測試

```sh
python3 -m unittest discover -s tests -v
```

測試使用暫存資料庫，涵蓋未 checkpoint 的 WAL、來源內容不變、唯讀限制、schema 變更、位置誤判、倒退進度、重複識別碼及輸出保護。
另外涵蓋 CFI 範圍、UTF-16 偏移、轉義及 URI 解碼、ID 不吻合、文字合併、ZIP／展開目錄一致性和資源路徑檢查。目前 28 項測試通過。

## 參考

[BearChao/apple-books-boox-sync](https://github.com/BearChao/apple-books-boox-sync) 提供 Apple Books / BOOX 實驗性同步的背景；本階段程式獨立撰寫，並以本機實際 schema 驗證。

[py-apple-books 的 annotation 模型](https://github.com/vgnshiyer/py-apple-books/blob/main/py_apple_books/models/annotation.py) 與 [reading-position 實作](https://github.com/vgnshiyer/py-apple-books/blob/main/py_apple_books/_api/positions.py) 提供 type 3、fraction 欄位及頁面資料的觀察依據；沒有將原始碼複製到本專案。
