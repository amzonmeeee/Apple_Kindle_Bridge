// Prints the text of each PDF page as a JSON array, using the system PDFKit.
import Foundation
import PDFKit

guard CommandLine.arguments.count == 2, let document = PDFDocument(url: URL(fileURLWithPath: CommandLine.arguments[1])) else {
    FileHandle.standardError.write("usage: pdftext file.pdf\n".data(using: .utf8)!)
    exit(2)
}
var pages: [String] = []
for index in 0..<document.pageCount {
    pages.append(document.page(at: index)?.string ?? "")
}
let data = try JSONSerialization.data(withJSONObject: pages)
FileHandle.standardOutput.write(data)
