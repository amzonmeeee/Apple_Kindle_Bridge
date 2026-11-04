// Marks a book as read or unread through the app's own menu, so the app records
// and syncs the change itself. Writing the database directly does not sync.
//   readstate kindle <asin> <title> read|unread
//   readstate books <title> <author> finished|reading
// Prints one JSON object: {"status": "done" | "already" | "not_found" | "error", ...}
import AppKit
import ApplicationServices

func say(_ object: [String: Any]) -> Never {
    FileHandle.standardOutput.write(try! JSONSerialization.data(withJSONObject: object))
    exit(object["status"] as? String == "error" ? 1 : 0)
}

func attr(_ e: AXUIElement, _ name: String) -> AnyObject? {
    var value: AnyObject?
    AXUIElementCopyAttributeValue(e, name as CFString, &value)
    return value
}

func walk(_ e: AXUIElement, _ depth: Int = 0, _ visit: (AXUIElement) -> Bool) -> AXUIElement? {
    if visit(e) { return e }
    if depth > 16 || (attr(e, kAXRoleAttribute) as? String) == "AXMenuBar" { return nil }
    for child in attr(e, kAXChildrenAttribute) as? [AXUIElement] ?? [] {
        if let found = walk(child, depth + 1, visit) { return found }
    }
    return nil
}

func wait(_ seconds: Double = 8, _ find: () -> AXUIElement?) -> AXUIElement? {
    let end = Date().addingTimeInterval(seconds)
    while Date() < end {
        if let found = find() { return found }
        usleep(250_000)
    }
    return nil
}

func press(_ e: AXUIElement, _ action: String = kAXPressAction) -> Bool {
    AXUIElementPerformAction(e, action as CFString) == .success
}

func launch(_ bundle: String) -> AXUIElement {
    guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundle) else {
        say(["status": "error", "message": "App not installed: \(bundle)"])
    }
    let semaphore = DispatchSemaphore(value: 0)
    var pid: pid_t = 0
    let config = NSWorkspace.OpenConfiguration()
    config.activates = true
    NSWorkspace.shared.openApplication(at: url, configuration: config) { app, _ in
        pid = app?.processIdentifier ?? 0
        semaphore.signal()
    }
    semaphore.wait()
    guard pid != 0 else { say(["status": "error", "message": "Could not open \(bundle)"]) }
    let app = AXUIElementCreateApplication(pid)
    _ = wait(15) { (attr(app, kAXWindowsAttribute) as? [AXUIElement])?.first }
    return app
}

guard AXIsProcessTrusted() else { say(["status": "error", "message": "Accessibility access is required"]) }
let args = Array(CommandLine.arguments.dropFirst())
guard args.count == 4 else { say(["status": "error", "message": "usage: readstate kindle|books ..."]) }

func id(_ e: AXUIElement) -> String { attr(e, kAXIdentifierAttribute) as? String ?? "" }
func desc(_ e: AXUIElement) -> String { attr(e, kAXDescriptionAttribute) as? String ?? "" }

if args[0] == "kindle" {
    let (asin, title, wanted) = (args[1], args[2], args[3] == "read")
    let app = launch("com.amazon.Lassen")
    // A book menu left open hides the library.
    if let cancel = walk(app, 0, { id($0) == "CancelBookSelectionAction" }) { _ = press(cancel); usleep(500_000) }
    if let library = walk(app, 0, { id($0) == "OOBAppChrome.library" }) { _ = press(library) }
    let cellID = "Cell(asin:\(asin))"
    var cell = wait(4) { walk(app, 0, { id($0) == cellID }) }
    var searched: AXUIElement?
    if cell == nil, let field = walk(app, 0, { (attr($0, kAXRoleAttribute) as? String) == "AXTextField" && desc($0).contains("Search") }) {
        // Off-screen books are not in the view; filter the library by title.
        AXUIElementSetAttributeValue(field, kAXValueAttribute as CFString, title as CFTypeRef)
        _ = press(field, "AXConfirm")
        searched = field
        cell = wait(8) { walk(app, 0, { id($0) == cellID }) }
    }
    defer { if let searched { AXUIElementSetAttributeValue(searched, kAXValueAttribute as CFString, "" as CFTypeRef) } }
    guard cell != nil else { say(["status": "not_found"]) }
    let target = wanted ? "MarkAsReadAction" : "MarkAsUnreadAction"
    let other = wanted ? "MarkAsUnreadAction" : "MarkAsReadAction"
    var action: AXUIElement?
    for _ in 0..<3 where action == nil {
        // The library redraws after switching tabs; use a fresh element each try.
        usleep(600_000)
        guard let fresh = walk(app, 0, { id($0) == cellID }) else { continue }
        _ = press(fresh, "AXShowMenu")
        action = wait(3) { walk(app, 0, { [target, other].contains(id($0)) }) }
    }
    guard let action else { say(["status": "error", "message": "Kindle menu did not open"]) }
    if id(action) == other {
        if let cancel = walk(app, 0, { id($0) == "CancelBookSelectionAction" }) { _ = press(cancel) }
        say(["status": "already"])
    }
    say(press(action) ? ["status": "done"] : ["status": "error", "message": "Could not press \(target)"])
}

if args[0] == "books" {
    let (title, author, wanted) = (args[1], args[2], args[3] == "finished")
    let app = launch("com.apple.iBooksX")
    if let open = walk(app, 0, { (attr($0, kAXRoleAttribute) as? String) == "AXMenu" }) { _ = press(open, "AXCancel") }
    if let all = walk(app, 0, { id($0) == "iBooksX.tabBar.libraryAll" }) { _ = press(all) }
    let prefix = author.isEmpty ? "\(title), " : "\(title), \(author),"
    func book() -> AXUIElement? {
        walk(app, 0, { (attr($0, kAXRoleAttribute) as? String) == "AXButton" && desc($0).hasPrefix(prefix) })
    }
    var found = wait(4) { book() }
    var pages = 0
    while found == nil && pages < 60 {
        // The grid lists only books near the screen; page through it.
        let cells = (walk(app, 0, { desc($0) == "All" && (attr($0, kAXRoleAttribute) as? String) == "AXGroup" })
            .flatMap { attr($0, kAXChildrenAttribute) as? [AXUIElement] } ?? []).filter { (attr($0, kAXRoleAttribute) as? String) == "AXButton" }
        guard let last = cells.last, press(last, "AXScrollDownByPage") else { break }
        usleep(400_000)
        found = book()
        pages += 1
    }
    guard let found else { say(["status": "not_found"]) }
    _ = press(found, "AXScrollToVisible")
    usleep(300_000)
    _ = press(found, "AXShowMenu")
    let target = wanted ? "markAsFinished" : "markAsStillReading"
    let other = wanted ? "markAsStillReading" : "markAsFinished"
    guard let item = wait(5, { walk(app, 0, { [target, other].contains(id($0)) && (attr($0, kAXRoleAttribute) as? String) == "AXMenuItem" }) }) else {
        say(["status": "error", "message": "Books menu did not open"])
    }
    if id(item) == other {
        if let menu = walk(app, 0, { (attr($0, kAXRoleAttribute) as? String) == "AXMenu" }) { _ = press(menu, "AXCancel") }
        say(["status": "already"])
    }
    say(press(item) ? ["status": "done"] : ["status": "error", "message": "Could not press \(target)"])
}
say(["status": "error", "message": "Unknown app \(args[0])"])
