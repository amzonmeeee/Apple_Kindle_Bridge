import AppKit
import ApplicationServices

/// Sends files through the Send to Kindle share extension, one file at a time.
/// The extension accepts only the first item of a multi-file share.
@MainActor
final class KindleShare: NSObject, NSSharingServiceDelegate {
    private var continuation: CheckedContinuation<Bool, Never>?

    /// The title is localized and can be upper case, such as "上傳至 KINDLE".
    static func service(for urls: [URL]) -> NSSharingService? {
        NSSharingService.sharingServices(forItems: urls).first { $0.title.range(of: "kindle", options: .caseInsensitive) != nil }
    }

    /// Press Send and the confirmation automatically when Accessibility access is granted.
    static var autoSend: Bool {
        get { UserDefaults.standard.object(forKey: "autoSend") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "autoSend") }
    }

    struct Outcome {
        var sent: [URL] = []
        var failed: [URL] = []
    }

    func send(_ urls: [URL], progress: (Int, Int, URL) -> Void) async throws -> Outcome {
        var outcome = Outcome()
        for (index, url) in urls.enumerated() {
            guard let service = Self.service(for: [url]) else {
                throw Backend.Failure(message: "找不到「Send to Kindle」分享功能，請確認 Kindle for Mac 已安裝並登入")
            }
            progress(index + 1, urls.count, url)
            service.delegate = self
            let before = Set(ShareClicker.windows().map(ShareClicker.key))
            let clicker = Self.autoSend && ShareClicker.trusted ? Task { await ShareClicker.run(ignoring: before) } : nil
            let ok = await withCheckedContinuation { (c: CheckedContinuation<Bool, Never>) in
                continuation = c
                service.perform(withItems: [url])
            }
            // The confirmation can appear after the extension reports success.
            if let clicker {
                if !ok { clicker.cancel() }
                _ = await clicker.value
            }
            if ok { outcome.sent.append(url) } else { outcome.failed.append(url) }
        }
        return outcome
    }

    var waiting: Bool { continuation != nil }

    /// Continue with the next file if the extension never reports back.
    func skipCurrent() { finish(false) }

    private func finish(_ ok: Bool) {
        continuation?.resume(returning: ok)
        continuation = nil
    }

    nonisolated func sharingService(_ sharingService: NSSharingService, didShareItems items: [Any]) {
        Task { @MainActor in self.finish(true) }
    }

    nonisolated func sharingService(_ sharingService: NSSharingService, didFailToShareItems items: [Any], error: Error) {
        Task { @MainActor in self.finish(false) }
    }
}

/// Presses buttons in the Send to Kindle sheet through Accessibility.
/// The extension's view is hosted in this app's own windows.
enum ShareClicker {
    static let sendLabels: Set<String> = ["send", "傳送", "上傳", "发送", "上传", "送出"]
    static let doneLabels: Set<String> = ["ok", "好", "確定", "确定", "done", "完成", "好的"]

    static var trusted: Bool { AXIsProcessTrusted() }

    static func requestAccess() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
    }

    static func attribute(_ element: AXUIElement, _ name: String) -> AnyObject? {
        var value: AnyObject?
        AXUIElementCopyAttributeValue(element, name as CFString, &value)
        return value
    }

    static func windows() -> [AXUIElement] {
        attribute(AXUIElementCreateApplication(getpid()), kAXWindowsAttribute) as? [AXUIElement] ?? []
    }

    static func key(_ window: AXUIElement) -> Int { Int(CFHash(window)) }

    static func buttons(in element: AXUIElement, depth: Int = 0) -> [AXUIElement] {
        guard depth < 14 else { return [] }
        let children = attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? []
        return children.flatMap { child -> [AXUIElement] in
            let role = attribute(child, kAXRoleAttribute) as? String
            return (role == kAXButtonRole ? [child] : []) + buttons(in: child, depth: depth + 1)
        }
    }

    static func label(_ button: AXUIElement) -> String {
        let title = attribute(button, kAXTitleAttribute) as? String ?? ""
        let description = attribute(button, kAXDescriptionAttribute) as? String ?? ""
        return (title.isEmpty ? description : title).trimmingCharacters(in: .whitespaces).lowercased()
    }

    /// Looks in windows that opened for this share only, so app alerts are never pressed.
    static func press(_ labels: Set<String>, ignoring: Set<Int>) -> Bool {
        for window in windows() where !ignoring.contains(key(window)) {
            if let button = buttons(in: window).first(where: { labels.contains(label($0)) }),
               (attribute(button, kAXEnabledAttribute) as? Bool ?? true) {
                return AXUIElementPerformAction(button, kAXPressAction as CFString) == .success
            }
        }
        return false
    }

    static func run(ignoring: Set<Int>) async {
        var sent = false
        var quiet = 0
        // Up to about 90 s in total. Stop once no share window has been open for 5 s.
        for _ in 0..<300 {
            if Task.isCancelled { return }
            try? await Task.sleep(nanoseconds: 300_000_000)
            if !sent {
                sent = press(sendLabels, ignoring: ignoring)
                continue
            }
            if press(doneLabels, ignoring: ignoring) { return }
            let open = windows().filter { !ignoring.contains(key($0)) && !buttons(in: $0).isEmpty }
            quiet = open.isEmpty ? quiet + 1 : 0
            if quiet > 16 { return }
        }
    }
}
