import AppKit
import SwiftUI
import UniformTypeIdentifiers

@main
struct BridgeApp: App {
    @StateObject private var model = AppModel()


    var body: some Scene {
        WindowGroup("Apple Kindle Bridge") {
            RootView()
                .environmentObject(model)
                .frame(minWidth: 760, minHeight: 560)
                .task { await model.start() }
        }
        .windowResizability(.contentMinSize)
    }
}

struct RootView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        ZStack {
            switch model.phase {
            case .loading: ProgressView("正在檢查…")
            case .onboarding: OnboardingView()
            case .firstImport: FirstImportView()
            case .main: MainView()
            }
            if let busy = model.busy {
                BusyOverlay(title: busy, detail: model.detail,
                            skip: model.sharing ? { model.share.skipCurrent() } : nil)
            }
        }
        .alert("發生錯誤", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("好") { model.error = nil }
        } message: { Text(model.error ?? "") }
        .alert("完成", isPresented: Binding(get: { model.notice != nil }, set: { if !$0 { model.notice = nil } })) {
            Button("好") { model.notice = nil }
        } message: { Text(model.notice ?? "") }
    }
}

struct BusyOverlay: View {
    let title: String
    let detail: String?
    var skip: (() -> Void)? = nil

    var body: some View {
        ZStack {
            Color.black.opacity(0.25).ignoresSafeArea()
            VStack(spacing: 10) {
                ProgressView()
                Text(title).font(.headline)
                if let detail { Text(detail).font(.callout).foregroundStyle(.secondary).lineLimit(2) }
                if let skip {
                    Button("略過這本", action: skip).padding(.top, 4)
                }
            }
            .padding(24)
            .frame(minWidth: 280)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
        }
    }
}

// MARK: - Onboarding

struct OnboardingView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("歡迎使用 Apple Kindle Bridge").font(.largeTitle.bold())
            Text("在 Apple Books 和 Kindle 之間同步閱讀位置、標註和筆記。先確認以下項目：")
                .foregroundStyle(.secondary)
            List(model.checks) { check in
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: check.ok ? (check.warning ? "exclamationmark.triangle.fill" : "checkmark.circle.fill") : "xmark.circle.fill")
                        .foregroundStyle(check.ok ? (check.warning ? .orange : .green) : .red)
                        .font(.title2)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(check.title).font(.headline)
                        if let detail = check.detail { Text(detail).font(.callout).foregroundStyle(.secondary) }
                    }
                    Spacer()
                    if !check.ok || check.warning, let action = check.action {
                        Button(Self.actionTitle(action)) { Task { await model.perform(action: action) } }
                    }
                }
                .padding(.vertical, 6)
            }
            .listStyle(.inset)
            HStack {
                Text("工具放在 ~/Library/Application Support/Apple Kindle Bridge，可在設定中一鍵移除。")
                    .font(.footnote).foregroundStyle(.secondary)
                Spacer()
                Button("重新檢查") { Task { await model.refreshChecks() } }
                Button("繼續") { Task { await model.finishOnboarding() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(!model.checks.allSatisfy(\.ok) || model.checks.isEmpty)
            }
        }
        .padding(28)
    }

    static func actionTitle(_ action: String) -> String {
        switch action {
        case "install": return "安裝"
        case "full_disk_access": return "打開系統設定"
        case "install_kindle": return "前往 App Store"
        case "open_kindle": return "打開 Kindle"
        case "accessibility": return "允許"
        default: return action
        }
    }
}

struct FirstImportView: View {
    @EnvironmentObject var model: AppModel
    @State private var toKindle: Set<String> = []
    @State private var toApple: Set<String> = []
    @State private var prepared = false

    var appleBooks: [Book] { model.appleOnly.filter(\.sendable) }
    var kindleBooks: [Book] { model.kindleOnly.filter { $0.kind == "transferable" } }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("匯入現有的書").font(.largeTitle.bold())
            Text("把只在一邊的書複製到另一邊，之後才能同步。預設全部匯入，可以取消勾選。受 DRM 保護的書不會列出。")
                .foregroundStyle(.secondary)
            HStack(alignment: .top, spacing: 16) {
                BookChecklist(title: "Apple Books → Kindle（\(appleBooks.count) 本）", books: appleBooks, selection: $toKindle)
                BookChecklist(title: "Kindle → Apple Books（\(kindleBooks.count) 本）", books: kindleBooks, selection: $toApple)
            }
            PDFLayoutOption()
            Text("傳到 Kindle 時會跳出 Send to Kindle 視窗。有輔助使用權限時 App 會自動按「傳送」，否則請手動按。書到了之後，要在 Kindle for Mac 裡下載才能配對。")
                .font(.footnote).foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("略過") { model.phase = .main; Task { await model.refreshStatus() } }
                Button("匯入") {
                    Task {
                        await model.sendToKindle(appleBooks.filter { toKindle.contains($0.id) })
                        await model.importToApple(kindleBooks.filter { toApple.contains($0.id) })
                        model.phase = .main
                        await model.refreshStatus()
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(toKindle.isEmpty && toApple.isEmpty)
            }
        }
        .padding(28)
        .onAppear {
            guard !prepared else { return }
            prepared = true
            toKindle = Set(appleBooks.map(\.id))
            toApple = Set(kindleBooks.map(\.id))
        }
    }
}

struct BookChecklist: View {
    let title: String
    let books: [Book]
    @Binding var selection: Set<String>

    var body: some View {
        VStack(alignment: .leading) {
            HStack {
                Text(title).font(.headline)
                Spacer()
                Button(selection.count == books.count ? "全不選" : "全選") {
                    selection = selection.count == books.count ? [] : Set(books.map(\.id))
                }
                .buttonStyle(.link)
                .disabled(books.isEmpty)
            }
            List(books) { book in
                Toggle(isOn: Binding(get: { selection.contains(book.id) },
                                     set: { if $0 { selection.insert(book.id) } else { selection.remove(book.id) } })) {
                    VStack(alignment: .leading) {
                        Text(book.title).lineLimit(1)
                        HStack(spacing: 6) {
                            if book.kind == "send_only" { Text("PDF・只傳送，不同步").font(.caption).foregroundStyle(.orange) }
                            if book.pending { Text("等待配對").font(.caption).foregroundStyle(.blue) }
                            if !book.author.isEmpty { Text(book.author).font(.caption).foregroundStyle(.secondary) }
                        }
                    }
                }
            }
            .listStyle(.bordered)
        }
    }
}

// MARK: - Main

struct MainView: View {
    var body: some View {
        TabView {
            SyncView().tabItem { Label("同步", systemImage: "arrow.triangle.2.circlepath") }
            LibraryView().tabItem { Label("書庫", systemImage: "books.vertical") }
            SettingsView().tabItem { Label("設定", systemImage: "gearshape") }
        }
        .padding(.top, 4)
    }
}

struct StateBadge: View {
    let pair: Pair

    var color: Color {
        switch pair.state {
        case "synced": return .green
        case "needs_sync": return .orange
        case "waiting_cloud": return .blue
        default: return .red
        }
    }

    var body: some View {
        Text(pair.stateLabel)
            .font(.caption.bold())
            .padding(.horizontal, 8).padding(.vertical, 3)
            .background(color.opacity(0.18), in: Capsule())
            .foregroundStyle(color)
    }
}

struct SyncView: View {
    @EnvironmentObject var model: AppModel
    @State private var confirm = false

    var pending: [Pair] { model.pairs.filter(\.needsSync) }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading) {
                    Text("同步狀態").font(.title2.bold())
                    Text(pending.isEmpty ? "所有已配對的書都同步了" : "\(pending.count) 本書需要同步。預設全部同步，可以逐項取消。")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button { Task { await model.refreshAll() } } label: { Label("重新檢查", systemImage: "arrow.clockwise") }
                Button("同步所選") { confirm = true }
                    .buttonStyle(.borderedProminent)
                    .disabled(pending.isEmpty)
            }
            .padding()
            Divider()
            if model.pairs.isEmpty {
                ContentUnavailableView("還沒有配對的書", systemImage: "books.vertical",
                                       description: Text("到「書庫」把書傳到另一邊。兩邊都有同一本書後會自動配對。"))
            } else {
                List {
                    ForEach(model.pairs) { pair in PairRow(pair: pair) }
                }
                .listStyle(.inset)
            }
        }
        .confirmationDialog("同步時會暫時關閉 Apple Books 和 Kindle for Mac，寫入前會自動備份。", isPresented: $confirm) {
            Button("開始同步") { Task { await model.sync(pending) } }
        }
    }
}

struct PairRow: View {
    @EnvironmentObject var model: AppModel
    @ObservedObject var pair: Pair
    @State private var expanded: Bool

    init(pair: Pair) {
        self.pair = pair
        _expanded = State(initialValue: pair.needsSync)
    }

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            VStack(alignment: .leading, spacing: 12) {
                if let error = pair.error { Text(error).foregroundStyle(.red).font(.callout) }
                PositionSection(pair: pair)
                if !pair.changes.isEmpty {
                    Text("標註與筆記（\(pair.changes.count)）").font(.headline)
                    ForEach(pair.changes) { change in ChangeRow(change: change) }
                }
                if pair.pendingUpload > 0 {
                    Label("\(pair.pendingUpload) 筆標註正在等 Kindle 上傳到雲端", systemImage: "icloud.and.arrow.up")
                        .font(.callout).foregroundStyle(.blue)
                }
                HStack {
                    Spacer()
                    Button("取消配對", role: .destructive) { Task { await model.unpair(pair) } }
                        .buttonStyle(.link)
                }
            }
            .padding(.leading, 8).padding(.vertical, 6)
        } label: {
            HStack {
                VStack(alignment: .leading) {
                    Text(pair.title).font(.headline)
                    if !pair.author.isEmpty { Text(pair.author).font(.caption).foregroundStyle(.secondary) }
                }
                Spacer()
                StateBadge(pair: pair)
            }
        }
        .padding(.vertical, 4)
    }
}

struct PositionSection: View {
    @ObservedObject var pair: Pair

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("閱讀位置").font(.headline)
                if pair.positionState == "synced" {
                    Label("一致", systemImage: "checkmark").foregroundStyle(.green).font(.callout)
                } else if pair.positionState == "conflict" {
                    Label("兩邊都移動過，預設採用較新的", systemImage: "exclamationmark.triangle").foregroundStyle(.orange).font(.callout)
                }
            }
            if let error = pair.positionError {
                Text(error).font(.callout).foregroundStyle(.red)
            } else {
                Excerpt(label: "Apple Books", text: pair.appleExcerpt, time: pair.appleUpdated)
                Excerpt(label: "Kindle", text: pair.kindleExcerpt, time: pair.kindleUpdated,
                        extra: pair.kindlePercent.map { String(format: "%.0f%%", $0) })
                if ["changed", "conflict"].contains(pair.positionState ?? "") {
                    Picker("同步方式", selection: $pair.positionTarget) {
                        Text("Apple Books 的位置 → Kindle").tag("kindle")
                        Text("Kindle 的位置 → Apple Books").tag("apple")
                        Text("不同步").tag("none")
                    }
                    .pickerStyle(.radioGroup)
                }
            }
        }
    }
}

struct Excerpt: View {
    let label: String
    let text: String?
    let time: String?
    var extra: String? = nil

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label).font(.caption.bold()).frame(width: 82, alignment: .leading)
            Text("「\(text ?? "—")…」").font(.callout).lineLimit(2)
            Spacer()
            if let extra { Text(extra).font(.caption).foregroundStyle(.secondary) }
            if let time { Text(Self.format(time)).font(.caption).foregroundStyle(.secondary) }
        }
    }

    static func format(_ iso: String) -> String {
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let date = parser.date(from: iso) ?? ISO8601DateFormatter().date(from: iso)
        guard let date else { return "" }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}

struct ChangeRow: View {
    @ObservedObject var change: Change

    var body: some View {
        HStack(alignment: .top) {
            Toggle("", isOn: $change.selected).labelsHidden().disabled(!change.available)
            VStack(alignment: .leading, spacing: 3) {
                Text(change.summary).font(.callout.bold())
                Text("「\(change.text)」").font(.callout).lineLimit(3)
                if let a = change.valueText("apple_value") { Text("Apple Books：\(a)").font(.caption).foregroundStyle(.secondary) }
                if let k = change.valueText("kindle_value") { Text("Kindle：\(k)").font(.caption).foregroundStyle(.secondary) }
                if change.canChooseTarget {
                    Picker("採用", selection: $change.target) {
                        Text("採用 Kindle 的版本").tag("apple")
                        Text("採用 Apple Books 的版本").tag("kindle")
                    }
                    .pickerStyle(.segmented)
                    .frame(maxWidth: 360)
                }
                if !change.available {
                    Text("暫時無法寫入 Kindle 的修改或刪除，需要先擷取一次 Kindle 的編輯格式。")
                        .font(.caption).foregroundStyle(.orange)
                }
            }
        }
        .padding(.vertical, 2)
    }
}


struct PDFLayoutOption: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Picker("PDF 版面", selection: $model.pdfAdjustable) {
                Text("保持原始版面（預設）").tag(false)
                Text("可調整版面").tag(true)
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 420)
            if !KindleShare.trusted {
                Text("沒有輔助使用權限時，App 無法替你選擇。請在 Send to Kindle 視窗裡手動選「PDF Options」。")
                    .font(.caption).foregroundStyle(.orange)
            }
        }
    }
}

// MARK: - Library

struct LibraryView: View {
    @EnvironmentObject var model: AppModel
    @State private var toKindle: Set<String> = []
    @State private var toApple: Set<String> = []
    @State private var showProtected = false

    var appleBooks: [Book] { model.appleOnly.filter(\.sendable) }
    var kindleBooks: [Book] { model.kindleOnly.filter { $0.kind == "transferable" } }
    /// Store editions and re-downloads can repeat a title; show each title and reason once.
    var unavailable: [Book] {
        var seen = Set<String>()
        let all = model.appleOnly.filter { !$0.sendable } + model.kindleOnly.filter { $0.kind != "transferable" } + model.protected
        return all.filter { seen.insert($0.title + "|" + Self.reason($0)).inserted }
            .sorted { (Self.reason($0), $0.title) < (Self.reason($1), $1.title) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("書庫").font(.title2.bold())
                Spacer()
                Button { addExternal() } label: { Label("加入外部書…", systemImage: "plus") }
                Button { Task { await model.refreshLibrary() } } label: { Label("重新整理", systemImage: "arrow.clockwise") }
            }
            HStack(alignment: .top, spacing: 16) {
                VStack {
                    BookChecklist(title: "只在 Apple Books（\(appleBooks.count)）", books: appleBooks, selection: $toKindle)
                    Button("傳到 Kindle（\(toKindle.count)）") {
                        let chosen = appleBooks.filter { toKindle.contains($0.id) }
                        toKindle = []
                        Task { await model.sendToKindle(chosen) }
                    }
                    .disabled(toKindle.isEmpty)
                }
                VStack {
                    BookChecklist(title: "只在 Kindle（\(kindleBooks.count)）", books: kindleBooks, selection: $toApple)
                    Button("匯入 Apple Books（\(toApple.count)）") {
                        let chosen = kindleBooks.filter { toApple.contains($0.id) }
                        toApple = []
                        Task { await model.importToApple(chosen) }
                    }
                    .disabled(toApple.isEmpty)
                }
            }
            PDFLayoutOption()
            DisclosureGroup("無法傳送的書（\(unavailable.count)）", isExpanded: $showProtected) {
                List(unavailable) { book in
                    HStack {
                        Text(book.title).lineLimit(1)
                        Spacer()
                        Text(Self.reason(book)).font(.caption).foregroundStyle(.secondary)
                    }
                }
                .frame(minHeight: 140)
            }
            Text("Mac 上的 Kindle 只列出已下載的書。只在雲端的 Kindle 書，請先在 Kindle for Mac 下載。")
                .font(.footnote).foregroundStyle(.secondary)
        }
        .padding()
    }

    static func reason(_ book: Book) -> String {
        switch book.kind {
        case "protected": return book.side == "kindle" ? "Kindle 商店購買（DRM）" : "Apple Books 商店購買（DRM）"
        case "too_large": return "超過 50MB（Send to Kindle 上限）"
        case "not_downloaded": return book.side == "kindle" ? "請先在 Kindle for Mac 下載" : "請先在 Apple Books 下載"
        case "unsupported": return book.side == "kindle" ? "不是 KFX 格式" : (book.reason ?? "不是 EPUB")
        default: return book.reason ?? ""
        }
    }

    func addExternal() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.allowedContentTypes = [UTType(filenameExtension: "epub") ?? .data]
        panel.message = "選擇 EPUB。會同時加入 Apple Books 和 Kindle。"
        guard panel.runModal() == .OK else { return }
        Task { await model.addExternal(panel.urls, toKindle: true, toApple: true) }
    }
}

// MARK: - Settings

struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @State private var confirmRemove = false

    var body: some View {
        Form {
            Section("環境") {
                ForEach(model.checks) { check in
                    HStack {
                        Image(systemName: check.ok ? (check.warning ? "exclamationmark.triangle.fill" : "checkmark.circle.fill") : "xmark.circle.fill")
                            .foregroundStyle(check.ok ? (check.warning ? .orange : .green) : .red)
                        Text(check.title)
                        Spacer()
                        if let detail = check.detail { Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
                    }
                }
                Button("重新檢查") { Task { await model.refreshChecks() } }
                Button("重新顯示初次設定") { model.phase = .onboarding }
            }
            Section("資料位置") {
                Text(Backend.home.path).font(.callout).textSelection(.enabled)
                HStack {
                    Button("在 Finder 中顯示") { NSWorkspace.shared.activateFileViewerSelecting([Backend.home]) }
                    Button("移除所有工具與資料…", role: .destructive) { confirmRemove = true }
                }
                Text("備份、同步紀錄和下載的工具都在這個資料夾。移除後不影響 Apple Books 和 Kindle 裡的書與標註。")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .confirmationDialog("移除所有下載的工具、備份和同步紀錄？", isPresented: $confirmRemove) {
            Button("移除", role: .destructive) { model.removeEverything() }
        }
    }
}
