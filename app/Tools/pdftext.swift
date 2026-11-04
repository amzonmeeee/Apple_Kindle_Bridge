// Reads PDF text with the system PDFKit.
//   pdftext file.pdf                 JSON array of page texts
//   pdftext --annotations file.pdf   JSON array of markup annotations
import Foundation
import PDFKit

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(2)
}

var args = Array(CommandLine.arguments.dropFirst())
let annotations = args.first == "--annotations"
if annotations { args.removeFirst() }
guard args.count == 1, let document = PDFDocument(url: URL(fileURLWithPath: args[0])) else {
    fail("usage: pdftext [--annotations] file.pdf")
}

func hex(_ color: NSColor?) -> String? {
    guard let rgb = color?.usingColorSpace(.deviceRGB) else { return nil }
    return String(format: "#%02X%02X%02X", Int(rgb.redComponent * 255), Int(rgb.greenComponent * 255), Int(rgb.blueComponent * 255))
}

var output: [Any] = []
for index in 0..<document.pageCount {
    guard let page = document.page(at: index) else { output.append(""); continue }
    if !annotations {
        output.append(page.string ?? "")
        continue
    }
    for annotation in page.annotations {
        let type = annotation.type ?? ""
        guard ["Highlight", "Underline", "StrikeOut", "Squiggly", "Text", "FreeText"].contains(type) else { continue }
        var text = ""
        if let quads = annotation.quadrilateralPoints, !quads.isEmpty {
            // Quad points are relative to the annotation bounds, four per line.
            var parts: [String] = []
            for start in stride(from: 0, to: quads.count - 3, by: 4) {
                let points = quads[start..<start + 4].map { $0.pointValue }
                let xs = points.map { $0.x + annotation.bounds.origin.x }, ys = points.map { $0.y + annotation.bounds.origin.y }
                let rect = CGRect(x: xs.min()!, y: ys.min()!, width: xs.max()! - xs.min()!, height: ys.max()! - ys.min()!)
                if let line = page.selection(for: rect.insetBy(dx: 0, dy: rect.height * 0.2))?.string { parts.append(line) }
            }
            text = parts.joined(separator: " ")
        } else if let selected = page.selection(for: annotation.bounds)?.string {
            text = selected
        }
        var entry: [String: Any] = ["page": index, "type": type, "text": text,
                                    "bounds": [annotation.bounds.origin.x, annotation.bounds.origin.y,
                                               annotation.bounds.width, annotation.bounds.height]]
        if let color = hex(annotation.color) { entry["color"] = color }
        if let contents = annotation.contents, !contents.isEmpty { entry["contents"] = contents }
        if let date = annotation.modificationDate { entry["modified"] = date.timeIntervalSince1970 }
        if let name = annotation.userName { entry["user"] = name }
        if let popup = annotation.popup?.contents, !popup.isEmpty { entry["popup"] = popup }
        output.append(entry)
    }
}
FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: output))
