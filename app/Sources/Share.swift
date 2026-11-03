import AppKit

/// Sends files through the Send to Kindle share extension, one file at a time.
/// The extension accepts only the first item of a multi-file share.
@MainActor
final class KindleShare: NSObject, NSSharingServiceDelegate {
    private var continuation: CheckedContinuation<Bool, Never>?

    /// The title is localized and can be upper case, such as "上傳至 KINDLE".
    static func service(for urls: [URL]) -> NSSharingService? {
        NSSharingService.sharingServices(forItems: urls).first { $0.title.range(of: "kindle", options: .caseInsensitive) != nil }
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
            let ok = await withCheckedContinuation { (c: CheckedContinuation<Bool, Never>) in
                continuation = c
                service.perform(withItems: [url])
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
