import Foundation

/// Runs the Python bridge inside the app's own runtime and reads its JSON lines.
struct Backend {
    static let home: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("Apple Kindle Bridge", isDirectory: true)
    }()
    static var resources: URL { Bundle.main.resourceURL! }
    static var bridgeSource: URL { resources.appendingPathComponent("bridge", isDirectory: true) }
    static var python: URL { home.appendingPathComponent("runtime/python/bin/python3") }

    static let pythonURL = "https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-aarch64-apple-darwin-install_only.tar.gz"
    static let pythonSHA256 = "fbf4afef53c2a6b72bb741bc06d5671a9dfaf87bd84e5aa73ac9b3d0d589f14e"

    struct Failure: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }

    static var environment: [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["AKB_HOME"] = home.path
        env["AKB_RESOURCES"] = resources.path
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        return env
    }

    /// Runs a tool and returns its standard output. Throws on a non-zero exit.
    @discardableResult
    static func run(_ tool: String, _ args: [String], cwd: URL? = nil) async throws -> String {
        try await withCheckedThrowingContinuation { continuation in
            let process = Process()
            process.executableURL = URL(fileURLWithPath: tool)
            process.arguments = args
            process.environment = environment
            if let cwd { process.currentDirectoryURL = cwd }
            let out = Pipe(), err = Pipe()
            process.standardOutput = out
            process.standardError = err
            process.terminationHandler = { p in
                let text = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                let error = String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                if p.terminationStatus == 0 {
                    continuation.resume(returning: text)
                } else {
                    continuation.resume(throwing: Failure(message: error.isEmpty ? text : error))
                }
            }
            do { try process.run() } catch { continuation.resume(throwing: error) }
        }
    }

    /// Runs a bridge module, sends progress lines to `progress`, returns the final result object.
    static func call(module: String = "apple_kindle_bridge.app", _ args: [String], input: Data? = nil,
                     progress: (@Sendable ([String: Any]) -> Void)? = nil) async throws -> Any {
        try await withCheckedThrowingContinuation { continuation in
            let process = Process()
            process.executableURL = python
            process.arguments = ["-s", "-m", module] + args
            process.environment = environment
            process.currentDirectoryURL = bridgeSource
            let out = Pipe(), err = Pipe(), stdin = Pipe()
            process.standardOutput = out
            process.standardError = err
            process.standardInput = stdin
            let collector = LineCollector()
            out.fileHandleForReading.readabilityHandler = { handle in
                for line in collector.feed(handle.availableData) {
                    guard let data = line.data(using: .utf8),
                          let event = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
                    collector.last = event
                    if event["event"] as? String != "result" { progress?(event) }
                }
            }
            process.terminationHandler = { _ in
                out.fileHandleForReading.readabilityHandler = nil
                for line in collector.feed(out.fileHandleForReading.readDataToEndOfFile()) {
                    if let data = line.data(using: .utf8),
                       let event = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                        collector.last = event
                    }
                }
                let stderr = String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                if let last = collector.last, last["event"] as? String == "result" {
                    continuation.resume(returning: last["result"] ?? [:])
                } else if let last = collector.last, last["event"] as? String == "error" {
                    continuation.resume(throwing: Failure(message: last["message"] as? String ?? "Unknown error"))
                } else if collector.last?["event"] as? String == "complete" {
                    continuation.resume(returning: collector.last ?? [:])
                } else {
                    continuation.resume(throwing: Failure(message: stderr.isEmpty ? "The helper stopped unexpectedly" : stderr))
                }
            }
            do {
                try process.run()
                if let input { stdin.fileHandleForWriting.write(input) }
                try? stdin.fileHandleForWriting.close()
            } catch {
                continuation.resume(throwing: error)
            }
        }
    }

    /// Downloads the private Python, then lets it install everything else.
    static func installRuntime(progress: @escaping @Sendable ([String: Any]) -> Void) async throws {
        let fm = FileManager.default
        try fm.createDirectory(at: home.appendingPathComponent("runtime"), withIntermediateDirectories: true)
        if !fm.fileExists(atPath: python.path) {
            progress(["event": "start", "label": "Python 3.12", "step": 1, "total": 8])
            let archive = home.appendingPathComponent("runtime/python.tar.gz")
            try await run("/usr/bin/curl", ["-fsSL", "--retry", "3", "-o", archive.path, pythonURL])
            let sum = try await run("/usr/bin/shasum", ["-a", "256", archive.path])
            guard sum.hasPrefix(pythonSHA256) else {
                try? fm.removeItem(at: archive)
                throw Failure(message: "Python download checksum mismatch")
            }
            let target = home.appendingPathComponent("runtime/python")
            try fm.createDirectory(at: target, withIntermediateDirectories: true)
            try await run("/usr/bin/tar", ["-xzf", archive.path, "-C", target.path, "--strip-components", "1"])
            try? fm.removeItem(at: archive)
        }
        _ = try await call(module: "apple_kindle_bridge.runtime_install", [], progress: progress)
    }
}

final class LineCollector: @unchecked Sendable {
    private var buffer = Data()
    private let lock = NSLock()
    var last: [String: Any]?

    func feed(_ data: Data) -> [String] {
        lock.lock(); defer { lock.unlock() }
        buffer.append(data)
        var lines: [String] = []
        while let range = buffer.firstRange(of: Data([0x0A])) {
            let line = buffer.subdata(in: buffer.startIndex..<range.lowerBound)
            buffer.removeSubrange(buffer.startIndex...range.lowerBound)
            if let text = String(data: line, encoding: .utf8), !text.isEmpty { lines.append(text) }
        }
        return lines
    }
}
