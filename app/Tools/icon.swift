// Draws the app icon: an open book, Apple Books orange on the left and Kindle
// paper on the right, under a two-way arc. Writes a 1024 px PNG.
import AppKit

let size: CGFloat = 1024
let image = NSImage(size: NSSize(width: size, height: size))
image.lockFocus()
let ctx = NSGraphicsContext.current!.cgContext

// macOS icon grid: an 824 px rounded square, centered.
let tile = CGRect(x: 100, y: 100, width: 824, height: 824)
let tilePath = CGPath(roundedRect: tile, cornerWidth: 185, cornerHeight: 185, transform: nil)
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -12), blur: 28, color: NSColor.black.withAlphaComponent(0.35).cgColor)
ctx.addPath(tilePath); ctx.setFillColor(NSColor.black.cgColor); ctx.fillPath()
ctx.restoreGState()
ctx.saveGState()
ctx.addPath(tilePath); ctx.clip()
let background = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
    colors: [NSColor(red: 0.20, green: 0.27, blue: 0.36, alpha: 1).cgColor,
             NSColor(red: 0.09, green: 0.13, blue: 0.18, alpha: 1).cgColor] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(background, start: CGPoint(x: 512, y: 924), end: CGPoint(x: 512, y: 100), options: [])
ctx.restoreGState()

func page(_ points: [CGPoint], control: CGPoint) -> CGPath {
    let p = CGMutablePath()
    p.move(to: points[0])
    p.addLine(to: points[1])
    p.addQuadCurve(to: points[2], control: control)
    p.addLine(to: points[3])
    p.closeSubpath()
    return p
}

// Spine at x = 512. Pages rise toward the outer edges.
let spineTop = CGPoint(x: 512, y: 560), spineBottom = CGPoint(x: 512, y: 250)
let left = page([spineBottom, spineTop, CGPoint(x: 236, y: 620), CGPoint(x: 236, y: 310)], control: CGPoint(x: 370, y: 640))
let right = page([spineBottom, spineTop, CGPoint(x: 788, y: 620), CGPoint(x: 788, y: 310)], control: CGPoint(x: 654, y: 640))

func fill(_ path: CGPath, _ top: NSColor, _ bottom: NSColor) {
    ctx.saveGState()
    ctx.addPath(path); ctx.clip()
    let g = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: [top.cgColor, bottom.cgColor] as CFArray, locations: [0, 1])!
    ctx.drawLinearGradient(g, start: CGPoint(x: 512, y: 640), end: CGPoint(x: 512, y: 250), options: [])
    ctx.restoreGState()
}
// Page block thickness under each page.
ctx.saveGState()
ctx.translateBy(x: 0, y: -22)
ctx.addPath(left); ctx.addPath(right)
ctx.setFillColor(NSColor(white: 0.85, alpha: 1).cgColor); ctx.fillPath()
ctx.restoreGState()
fill(left, NSColor(red: 1.0, green: 0.72, blue: 0.25, alpha: 1), NSColor(red: 1.0, green: 0.48, blue: 0.0, alpha: 1))
fill(right, NSColor(red: 0.98, green: 0.97, blue: 0.93, alpha: 1), NSColor(red: 0.88, green: 0.86, blue: 0.80, alpha: 1))
// Text lines on the Kindle page.
ctx.setStrokeColor(NSColor(white: 0.55, alpha: 0.55).cgColor)
ctx.setLineWidth(10); ctx.setLineCap(.round)
for i in 0..<4 {
    let y = CGFloat(500 - i * 52)
    ctx.move(to: CGPoint(x: 560, y: y + 12)); ctx.addLine(to: CGPoint(x: 740, y: y + 32)); ctx.strokePath()
}
// Spine shadow.
ctx.setStrokeColor(NSColor.black.withAlphaComponent(0.25).cgColor); ctx.setLineWidth(6)
ctx.move(to: spineBottom); ctx.addLine(to: spineTop); ctx.strokePath()

// Two-way arc over the book.
let arcCenter = CGPoint(x: 512, y: 600), radius: CGFloat = 250
ctx.setStrokeColor(NSColor.white.cgColor); ctx.setLineWidth(30); ctx.setLineCap(.round)
ctx.addArc(center: arcCenter, radius: radius, startAngle: .pi * 0.86, endAngle: .pi * 0.14, clockwise: true)
ctx.strokePath()
func arrow(at angle: CGFloat, pointing direction: CGFloat) {
    let tip = CGPoint(x: arcCenter.x + radius * cos(angle), y: arcCenter.y + radius * sin(angle))
    // Tangent direction along the arc.
    let tangent = angle + direction * .pi / 2
    let back = CGPoint(x: tip.x - 70 * cos(tangent), y: tip.y - 70 * sin(tangent))
    let normal = tangent + .pi / 2
    let a = CGPoint(x: back.x + 48 * cos(normal), y: back.y + 48 * sin(normal))
    let b = CGPoint(x: back.x - 48 * cos(normal), y: back.y - 48 * sin(normal))
    let tipOut = CGPoint(x: tip.x + 24 * cos(tangent), y: tip.y + 24 * sin(tangent))
    ctx.move(to: tipOut); ctx.addLine(to: a); ctx.addLine(to: b); ctx.closePath()
    ctx.setFillColor(NSColor.white.cgColor); ctx.fillPath()
}
arrow(at: .pi * 0.86, pointing: 1)
arrow(at: .pi * 0.14, pointing: -1)
image.unlockFocus()

let rep = NSBitmapImageRep(data: image.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
