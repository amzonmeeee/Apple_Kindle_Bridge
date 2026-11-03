import AppKit
import Foundation

struct Check: Identifiable {
    let id: String
    let ok: Bool
    let warning: Bool
    let title: String
    let detail: String?
    let action: String?
}

struct Book: Identifiable, Hashable {
    let id: String
    let title: String
    let author: String
    let kind: String
    let reason: String?
    let side: String
    let pending: Bool
}

final class Change: Identifiable, ObservableObject {
    let id: String
    let kind: String
    let text: String
    let supported: Bool
    let reason: String?
    let raw: [String: Any]
    let canChooseTarget: Bool
    @Published var selected: Bool
    @Published var target: String

    init(_ raw: [String: Any]) {
        self.raw = raw
        id = raw["id"] as? String ?? UUID().uuidString
        kind = raw["kind"] as? String ?? ""
        text = raw["text"] as? String ?? ""
        supported = raw["supported"] as? Bool ?? false
        reason = raw["reason"] as? String
        selected = raw["selected"] as? Bool ?? false
        target = raw["target"] as? String ?? "apple"
        canChooseTarget = ["differs", "conflict"].contains(kind)
    }

    /// Only Apple-side edits are available until the Kindle edit format is captured.
    var targetSupported: Bool { kind == "add" || target == "apple" }
    var available: Bool { canChooseTarget ? targetSupported : supported }

    var summary: String {
        switch (kind, target) {
        case ("add", "kindle"): return "新增到 Kindle"
        case ("add", "apple"): return "新增到 Apple Books"
        case ("update", "kindle"): return "更新 Kindle"
        case ("update", "apple"): return "更新 Apple Books"
        case ("delete", "kindle"): return "從 Kindle 刪除"
        case ("delete", "apple"): return "從 Apple Books 刪除"
        case ("differs", _): return "兩邊內容不同"
        case ("conflict", _): return "兩邊都改過"
        default: return kind
        }
    }

    func valueText(_ key: String) -> String? {
        guard let value = raw[key] as? [String: Any] else { return key == "apple_value" && kind == "conflict" ? "已刪除" : nil }
        let note = (value["note"] as? String).map { "筆記：\($0)" } ?? "無筆記"
        let color = Colors.name(value["color"] as? String)
        return "\(color)・\(note)"
    }

    var payload: [String: Any] {
        var out = raw
        out["target"] = target
        return out
    }
}

enum Colors {
    static func name(_ value: String?) -> String {
        switch value {
        case "yellow": return "黃色"
        case "blue": return "藍色"
        case "pink": return "粉紅色"
        case "orange": return "橘色"
        case "green": return "綠色"
        case "purple": return "紫色"
        default: return value ?? "無顏色"
        }
    }
}

final class Pair: Identifiable, ObservableObject {
    let id: String
    let kindleId: String
    let title: String
    let author: String
    let state: String
    let error: String?
    let positionState: String?
    let positionError: String?
    let appleExcerpt: String?
    let kindleExcerpt: String?
    let kindlePercent: Double?
    let appleUpdated: String?
    let kindleUpdated: String?
    let changes: [Change]
    let pendingUpload: Int
    @Published var positionTarget: String

    init(_ raw: [String: Any]) {
        id = raw["apple_id"] as? String ?? ""
        kindleId = raw["kindle_id"] as? String ?? ""
        title = raw["title"] as? String ?? ""
        author = raw["author"] as? String ?? ""
        state = raw["state"] as? String ?? "error"
        error = raw["error"] as? String
        let position = raw["position"] as? [String: Any] ?? [:]
        positionState = position["state"] as? String
        positionError = position["error"] as? String
        let apple = position["apple"] as? [String: Any] ?? [:]
        let kindle = position["kindle"] as? [String: Any] ?? [:]
        appleExcerpt = apple["excerpt"] as? String
        kindleExcerpt = kindle["excerpt"] as? String
        kindlePercent = kindle["percent"] as? Double
        appleUpdated = apple["updated"] as? String
        kindleUpdated = kindle["updated"] as? String
        positionTarget = ["changed", "conflict"].contains(positionState ?? "") ? (position["default_target"] as? String ?? "none") : "none"
        let highlights = raw["highlights"] as? [String: Any] ?? [:]
        changes = (highlights["changes"] as? [[String: Any]] ?? []).map(Change.init)
        pendingUpload = highlights["pending_upload"] as? Int ?? 0
    }

    var needsSync: Bool { state == "needs_sync" }

    var stateLabel: String {
        switch state {
        case "synced": return "已同步"
        case "needs_sync": return "需要同步"
        case "waiting_cloud": return "等待雲端"
        case "unavailable": return "無法使用"
        default: return "錯誤"
        }
    }

    func plan() -> [String: Any]? {
        let chosen = changes.filter { $0.selected && $0.available }
        let position = positionTarget == "none" ? nil : positionTarget
        if chosen.isEmpty && position == nil && positionState != "synced" { return nil }
        var plan: [String: Any] = ["apple_id": id, "kindle_id": kindleId,
                                   "changes": chosen.map(\.payload),
                                   "position_synced": positionState == "synced"]
        if let position { plan["position"] = position }
        return plan
    }
}

@MainActor
final class AppModel: ObservableObject {
    enum Phase { case loading, onboarding, firstImport, main }

    @Published var phase: Phase = .loading
    @Published var checks: [Check] = []
    @Published var pairs: [Pair] = []
    @Published var appleOnly: [Book] = []
    @Published var kindleOnly: [Book] = []
    @Published var protected: [Book] = []
    @Published var busy: String?
    @Published var detail: String?
    @Published var error: String?
    @Published var notice: String?

    private let defaults = UserDefaults.standard
    var onboarded: Bool {
        get { defaults.bool(forKey: "onboarded") }
        set { defaults.set(newValue, forKey: "onboarded") }
    }

    func start() async {
        await refreshChecks()
        if checks.allSatisfy(\.ok) && onboarded {
            phase = .main
            await refreshAll()
        } else {
            phase = .onboarding
        }
    }

    func work(_ title: String, _ body: () async throws -> Void) async {
        busy = title
        detail = nil
        defer { busy = nil; detail = nil }
        do { try await body() } catch { self.error = error.localizedDescription }
    }

    nonisolated func progress(_ event: [String: Any]) {
        Task { @MainActor in
            if let label = event["label"] as? String, let step = event["step"] as? Int, let total = event["total"] as? Int {
                self.detail = "\(step)/\(total)  \(label)"
            } else if let title = event["title"] as? String {
                self.detail = title
            } else if let step = event["step"] as? String {
                self.detail = step
            }
        }
    }

    func refreshChecks() async {
        let runtimeReady = FileManager.default.fileExists(atPath: Backend.python.path)
        guard runtimeReady else {
            checks = [Check(id: "runtime", ok: false, warning: false, title: "內建工具",
                            detail: "第一次使用需要下載約 500MB 的工具，會放在 App 自己的資料夾", action: "install")]
            return
        }
        do {
            let result = try await Backend.call(["doctor"]) as? [String: Any] ?? [:]
            checks = (result["checks"] as? [[String: Any]] ?? []).map { raw in
                Check(id: raw["key"] as? String ?? "", ok: raw["ok"] as? Bool ?? false,
                      warning: raw["warning"] as? Bool ?? false,
                      title: Self.checkTitle(raw), detail: Self.checkDetail(raw),
                      action: raw["action"] as? String)
            }
        } catch {
            checks = [Check(id: "runtime", ok: false, warning: false, title: "內建工具",
                            detail: "工具不完整，請重新安裝：\(error.localizedDescription)", action: "install")]
        }
    }

    static func checkTitle(_ raw: [String: Any]) -> String {
        switch raw["key"] as? String {
        case "runtime": return "內建工具"
        case "apple_access": return "讀取 Apple Books 資料"
        case "kindle_app": return "Kindle for Mac"
        case "kindle_version": return (raw["title"] as? String ?? "").replacingOccurrences(of: "Kindle version", with: "Kindle 版本")
        case "kindle_access": return "讀取 Kindle 資料"
        case "kindle_signed_in": return "Kindle 帳號"
        default: return raw["title"] as? String ?? ""
        }
    }

    static func checkDetail(_ raw: [String: Any]) -> String? {
        let ok = raw["ok"] as? Bool ?? false
        switch raw["key"] as? String {
        case "runtime": return ok ? "已安裝" : "缺少部分工具，按「安裝」下載"
        case "apple_access", "kindle_access":
            return ok ? nil : "請在「系統設定 → 隱私權與安全性 → 完整磁碟取用權限」打開本 App，然後重新開啟 App"
        case "kindle_app": return ok ? nil : "請從 Mac App Store 下載 Kindle"
        case "kindle_version": return (raw["warning"] as? Bool ?? false) ? "這個版本還沒測試過。第一次同步後，請在 Kindle 上確認結果" : "已測試的版本"
        case "kindle_signed_in": return ok ? nil : "請打開 Kindle for Mac 並登入 Amazon 帳號"
        default: return raw["detail"] as? String
        }
    }

    func perform(action: String) async {
        switch action {
        case "install":
            await work("正在下載工具") {
                try await Backend.installRuntime { [weak self] event in self?.progress(event) }
            }
            await refreshChecks()
        case "full_disk_access":
            NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_AllFiles")!)
        case "install_kindle":
            NSWorkspace.shared.open(URL(string: "macappstore://apps.apple.com/app/id405399194")!)
        case "open_kindle":
            NSWorkspace.shared.open(URL(fileURLWithPath: "/Applications/Amazon Kindle.app"))
        default: break
        }
    }

    func finishOnboarding() async {
        onboarded = true
        await refreshLibrary()
        phase = (appleOnly.contains { $0.kind == "transferable" } || kindleOnly.contains { $0.kind == "transferable" }) ? .firstImport : .main
        if phase == .main { await refreshStatus() }
    }

    func refreshAll() async {
        await refreshLibrary()
        await refreshStatus()
    }

    func refreshLibrary() async {
        do {
            let result = try await Backend.call(["library"]) as? [String: Any] ?? [:]
            func books(_ key: String, side: String) -> [Book] {
                (result[key] as? [[String: Any]] ?? []).map { raw in
                    Book(id: raw["id"] as? String ?? "", title: raw["title"] as? String ?? "",
                         author: raw["author"] as? String ?? "", kind: raw["kind"] as? String ?? "",
                         reason: raw["reason"] as? String, side: raw["side"] as? String ?? side,
                         pending: raw["pending_import"] != nil)
                }
            }
            appleOnly = books("apple_only", side: "apple").sorted { $0.title < $1.title }
            kindleOnly = books("kindle_only", side: "kindle").sorted { $0.title < $1.title }
            protected = books("protected", side: "apple")
        } catch {
            self.error = error.localizedDescription
        }
    }

    func refreshStatus() async {
        await work("正在檢查同步狀態") {
            let result = try await Backend.call(["status"]) { [weak self] event in self?.progress(event) } as? [String: Any] ?? [:]
            let list = (result["pairs"] as? [[String: Any]] ?? []).map(Pair.init)
            pairs = list.sorted { ($0.needsSync ? 0 : 1, $0.title) < ($1.needsSync ? 0 : 1, $1.title) }
        }
    }

    func sync(_ selected: [Pair]) async {
        let plans = selected.compactMap { $0.plan() }
        guard !plans.isEmpty else { notice = "沒有選擇要同步的項目"; return }
        var skipped: [String] = []
        await work("正在同步") {
            for plan in plans {
                let data = try JSONSerialization.data(withJSONObject: plan)
                let result = try await Backend.call(["apply"], input: data) { [weak self] event in self?.progress(event) } as? [String: Any] ?? [:]
                for item in result["skipped"] as? [[String: Any]] ?? [] {
                    skipped.append(item["reason"] as? String ?? "")
                }
            }
        }
        if error == nil {
            notice = skipped.isEmpty ? "同步完成。請等兩邊和雲端同步好，再到裝置上確認。" : "同步完成，有 \(skipped.count) 項略過：\(Set(skipped).joined(separator: "；"))"
        }
        await refreshAll()
    }

    func sendToKindle(_ books: [Book]) async {
        guard !books.isEmpty else { return }
        await work("正在準備檔案") {
            let result = try await Backend.call(["package-for-kindle"] + books.map(\.id)) as? [String: Any] ?? [:]
            let files = (result["files"] as? [[String: Any]] ?? [])
            let large = files.filter { $0["too_large"] as? Bool ?? false }.compactMap { $0["title"] as? String }
            let urls = files.filter { !($0["too_large"] as? Bool ?? false) }.compactMap { ($0["path"] as? String).map(URL.init(fileURLWithPath:)) }
            if !large.isEmpty { notice = "超過 200MB，Send to Kindle 不接受：\(large.joined(separator: "、"))" }
            guard !urls.isEmpty else { return }
            guard let service = NSSharingService.sharingServices(forItems: urls).first(where: { $0.title.contains("Kindle") }) else {
                throw Backend.Failure(message: "找不到「Send to Kindle」分享功能，請確認 Kindle for Mac 已安裝並登入")
            }
            service.perform(withItems: urls)
        }
        if error == nil && notice == nil {
            notice = "已交給 Send to Kindle。書出現在 Kindle for Mac 後，請在 Kindle 裡下載它，App 會自動配對。"
        }
        await refreshLibrary()
    }

    func importToApple(_ books: [Book]) async {
        guard !books.isEmpty else { return }
        await work("正在轉換並加入 Apple Books") {
            _ = try await Backend.call(["import-to-apple"] + books.map(\.id)) { [weak self] event in self?.progress(event) }
        }
        if error == nil { notice = "已加入 Apple Books。App 會在書出現後自動配對。" }
        await refreshLibrary()
    }

    func addExternal(_ urls: [URL], toKindle: Bool, toApple: Bool) async {
        if toApple {
            for url in urls { _ = try? await NSWorkspace.shared.open([url], withApplicationAt: URL(fileURLWithPath: "/System/Applications/Books.app"), configuration: NSWorkspace.OpenConfiguration()) }
        }
        if toKindle {
            if let service = NSSharingService.sharingServices(forItems: urls).first(where: { $0.title.contains("Kindle") }) {
                service.perform(withItems: urls)
            } else {
                error = "找不到「Send to Kindle」分享功能"
            }
        }
        notice = "已送出。兩邊都出現同一本書後，App 會依書名自動配對。"
    }

    func unpair(_ pair: Pair) async {
        await work("正在取消配對") { _ = try await Backend.call(["unpair", pair.id]) }
        await refreshAll()
    }

    func removeEverything() {
        try? FileManager.default.removeItem(at: Backend.home)
        onboarded = false
        phase = .onboarding
        Task { await refreshChecks() }
    }
}
