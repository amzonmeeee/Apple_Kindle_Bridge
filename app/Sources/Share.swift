import AppKit
import ApplicationServices

/// Sends files through the Send to Kindle share extension, one file at a time.
///
/// The extension takes only the first item of a multi-file share, and it does
/// not report a reliable result: Close and Send look the same to its delegate.
/// Its sheet is hosted in this app's own windows, so with Accessibility access
/// the app reads it. A "File sent" message is the only proof of a send.
@MainActor
final class KindleShare: NSObject, NSSharingServiceDelegate {
    private var skipRequested = false

    /// The title is localized and can be upper case, such as "上傳至 KINDLE".
    static func service(for urls: [URL]) -> NSSharingService? {
        NSSharingService.sharingServices(forItems: urls).first { $0.title.range(of: "kindle", options: .caseInsensitive) != nil }
    }

    static var autoSend: Bool {
        get { UserDefaults.standard.object(forKey: "autoSend") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "autoSend") }
    }

    static var trusted: Bool { AXIsProcessTrusted() }

    static func requestAccess() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
    }

    struct Outcome {
        var sent: [URL] = []
        var failed: [URL] = []
        var unconfirmed: [URL] = []
    }

    func skipCurrent() { skipRequested = true }

    func send(_ urls: [URL], pdfAdjustable: Bool, progress: (Int, Int, URL) -> Void) async throws -> Outcome {
        var outcome = Outcome()
        for (index, url) in urls.enumerated() {
            guard let service = Self.service(for: [url]) else {
                throw Backend.Failure(message: "找不到「Send to Kindle」分享功能，請確認 Kindle for Mac 已安裝並登入")
            }
            progress(index + 1, urls.count, url)
            skipRequested = false
            service.delegate = self
            service.perform(withItems: [url])
            let isPDF = url.pathExtension.lowercased() == "pdf"
            switch await watch(adjustPDF: isPDF && pdfAdjustable) {
            case .sent: outcome.sent.append(url)
            case .failed: outcome.failed.append(url)
            case .unknown: outcome.unconfirmed.append(url)
            }
        }
        return outcome
    }

    enum Result { case sent, failed, unknown }

    private func watch(adjustPDF: Bool) async -> Result {
        let readable = Self.trusted
        let automatic = readable && Self.autoSend
        var seen = false, sendPressed = false, confirmed = false
        var layoutStep = adjustPDF ? 0 : 3
        var gone = 0
        for tick in 0..<1200 {  // about 6 minutes; a manual send can take a while
            if skipRequested { Sheet.closeAll(); return confirmed ? .sent : .failed }
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard readable else {
                // Without Accessibility the sheet cannot be read; wait for it to close.
                if Sheet.otherWindowVisible() { seen = true; gone = 0 } else if seen { gone += 1 }
                if (seen && gone > 3) || (!seen && tick > 60) { return .unknown }
                continue
            }
            let sheets = Sheet.windows()
            if sheets.isEmpty {
                if seen { gone += 1 }
                if (seen && gone > 5) || (!seen && tick > 60) { return confirmed ? .sent : .failed }
                continue
            }
            seen = true
            gone = 0
            if Sheet.hasText(["file sent", "已傳送", "已发送"], in: sheets) {
                confirmed = true
                if automatic { _ = Sheet.press(exact: ["ok", "好", "確定", "确定"], in: sheets) }
                continue
            }
            guard automatic else { continue }
            if layoutStep == 0, Sheet.press(prefix: "keep original layout", in: sheets) { layoutStep = 1; continue }
            if layoutStep == 1, Sheet.press(prefix: "make layout adjustable", in: sheets) { layoutStep = 2; continue }
            if layoutStep == 2, Sheet.press(prefix: "back button", in: sheets) { layoutStep = 3; continue }
            if layoutStep == 3, !sendPressed, Sheet.press(exact: ["send", "傳送", "上傳", "发送", "上传"], in: sheets) {
                sendPressed = true
            }
        }
        return confirmed ? .sent : .failed
    }

    nonisolated func sharingService(_ sharingService: NSSharingService, didShareItems items: [Any]) {}
    nonisolated func sharingService(_ sharingService: NSSharingService, didFailToShareItems items: [Any], error: Error) {}
}

/// Accessibility reads of the Send to Kindle sheet inside this app.
enum Sheet {
    static func attribute(_ element: AXUIElement, _ name: String) -> AnyObject? {
        var value: AnyObject?
        AXUIElementCopyAttributeValue(element, name as CFString, &value)
        return value
    }

    /// The app's own SwiftUI window, and the alerts attached to it, are never touched.
    static func isMain(_ window: AXUIElement) -> Bool {
        (attribute(window, kAXIdentifierAttribute) as? String ?? "").hasPrefix("SwiftUI")
    }

    static func windows() -> [AXUIElement] {
        let all = attribute(AXUIElementCreateApplication(getpid()), kAXWindowsAttribute) as? [AXUIElement] ?? []
        return all.filter { !isMain($0) && !elements(in: $0, role: kAXButtonRole as String).isEmpty }
    }

    static func otherWindowVisible() -> Bool {
        NSApp.windows.contains { $0.isVisible && !($0.identifier?.rawValue ?? "").hasPrefix("SwiftUI") }
    }

    static func elements(in element: AXUIElement, role: String, depth: Int = 0) -> [AXUIElement] {
        guard depth < 16 else { return [] }
        let children = attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? []
        return children.flatMap { child -> [AXUIElement] in
            ((attribute(child, kAXRoleAttribute) as? String) == role ? [child] : []) + elements(in: child, role: role, depth: depth + 1)
        }
    }

    static func label(_ element: AXUIElement) -> String {
        let title = attribute(element, kAXTitleAttribute) as? String ?? ""
        let description = attribute(element, kAXDescriptionAttribute) as? String ?? ""
        return (title.isEmpty ? description : title).trimmingCharacters(in: .whitespaces).lowercased()
    }

    static func hasText(_ needles: [String], in windows: [AXUIElement]) -> Bool {
        windows.contains { window in
            elements(in: window, role: kAXStaticTextRole as String).contains { text in
                let value = ((attribute(text, kAXValueAttribute) as? String) ?? label(text)).lowercased()
                return needles.contains { value.contains($0) }
            }
        }
    }

    static func press(_ match: (String) -> Bool, in windows: [AXUIElement]) -> Bool {
        for window in windows {
            if let button = elements(in: window, role: kAXButtonRole as String).first(where: { match(label($0)) }) {
                return AXUIElementPerformAction(button, kAXPressAction as CFString) == .success
            }
        }
        return false
    }

    static func press(exact labels: Set<String>, in windows: [AXUIElement]) -> Bool {
        press({ labels.contains($0) }, in: windows)
    }

    static func press(prefix: String, in windows: [AXUIElement]) -> Bool {
        press({ $0.hasPrefix(prefix) }, in: windows)
    }

    static func closeAll() {
        _ = press(exact: ["close", "關閉", "关闭", "ok"], in: windows())
    }
}
