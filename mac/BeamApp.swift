// Beam.app - a native window around the Beam page.
//
// It starts ~/beam/server.py on launch with BEAM_TRUST_LOOPBACK=1, reads the
// port back out of the server's own banner, waits for that port to answer, and
// stops the server again on quit. The window talks to 127.0.0.1, never to the
// LAN address: loopback is the one caller the server tells the PIN and the QR
// to, and it is also a secure origin, so the page's copy-link button works.

import AppKit
import WebKit

// MARK: - Where things live

let projectDir: String = {
    if let p = Bundle.main.object(forInfoDictionaryKey: "BeamProjectDir") as? String,
       !p.isEmpty {
        return (p as NSString).expandingTildeInPath
    }
    return ("~/beam" as NSString).expandingTildeInPath
}()

// The Python that ships with the machine. A GUI app inherits a bare PATH
// (/usr/bin:/bin:/usr/sbin:/sbin), so Homebrew's python3 is not reachable here
// and the interpreter has to be named outright. server.py is standard library
// only and runs on 3.9, which is what /usr/bin/python3 is.
let pythonCandidates = ["/usr/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3"]

func firstPython() -> String? {
    pythonCandidates.first { FileManager.default.isExecutableFile(atPath: $0) }
}


// MARK: - Port 8080, and who is holding it

/// True if nothing can bind the port right now - i.e. something is listening.
func portIsBusy(_ port: UInt16) -> Bool {
    let fd = socket(AF_INET, SOCK_STREAM, 0)
    guard fd >= 0 else { return true }
    defer { close(fd) }
    var yes: Int32 = 1
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, socklen_t(MemoryLayout<Int32>.size))
    var addr = sockaddr_in()
    addr.sin_family = sa_family_t(AF_INET)
    addr.sin_port = port.bigEndian
    addr.sin_addr.s_addr = INADDR_ANY
    let rc = withUnsafePointer(to: &addr) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            Darwin.bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
        }
    }
    return rc != 0
}

func run(_ tool: String, _ args: [String]) -> String {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: tool)
    p.arguments = args
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = Pipe()
    do { try p.run() } catch { return "" }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return String(data: data, encoding: .utf8) ?? ""
}

/// The pid listening on a port, if any.
func pidListening(on port: Int) -> Int32? {
    let out = run("/usr/sbin/lsof", ["-nP", "-iTCP:\(port)", "-sTCP:LISTEN", "-t"])
    return out.split(whereSeparator: \.isNewline).compactMap { Int32($0.trimmingCharacters(in: .whitespaces)) }.first
}

/// A leftover server from a force-quit holds the port, and the next launch
/// would quietly slide to 8081 - which is the address the phone no longer has.
/// So take the port back, but only from something that really is a Beam server.
func reclaimPort(_ port: Int) {
    guard portIsBusy(UInt16(port)), let pid = pidListening(on: port) else { return }
    let cmd = run("/bin/ps", ["-p", "\(pid)", "-o", "command="])
    guard cmd.contains("server.py") && cmd.contains("beam") else { return }   // not ours; leave it
    kill(pid, SIGTERM)
    let deadline = Date().addingTimeInterval(3)
    while Date() < deadline && portIsBusy(UInt16(port)) { usleep(100_000) }
    if kill(pid, 0) == 0 && portIsBusy(UInt16(port)) { kill(pid, SIGKILL); usleep(300_000) }
}

// MARK: - App

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate,
                         WKUIDelegate, WKDownloadDelegate {

    var window: NSWindow!
    var web: WKWebView!
    var cover: NSView!          // the "starting" panel, on top until the page loads
    var message: NSTextField!
    var spinner: NSProgressIndicator!
    var detail: NSTextField!

    let server = Process()
    var stdoutBuffer = ""
    var port: Int?
    var pageLoaded = false
    var probeTries = 0
    var signalSources: [DispatchSourceSignal] = []

    // MARK: Launch

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        catchSignals()
        buildWindow()
        startServer()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ note: Notification) { stopServer() }

    // MARK: Window

    func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1180, height: 820),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Beam"
        window.minSize = NSSize(width: 420, height: 480)
        window.center()
        window.setFrameAutosaveName("BeamWindow")

        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.autoresizingMask = [.width, .height]
        web.setValue(false, forKey: "drawsBackground")

        let content = NSView(frame: window.contentView!.bounds)
        content.autoresizingMask = [.width, .height]
        web.frame = content.bounds
        content.addSubview(web)

        // The cover sits over the web view until the first page load lands, so
        // the user never sees a white rectangle or a connection error.
        cover = NSView(frame: content.bounds)
        cover.autoresizingMask = [.width, .height]
        cover.wantsLayer = true
        cover.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor

        spinner = NSProgressIndicator()
        spinner.style = .spinning
        spinner.controlSize = .small
        spinner.startAnimation(nil)

        message = label("Starting Beam...", size: 13, bold: true)
        detail = label("", size: 11, bold: false)
        detail.textColor = .secondaryLabelColor

        let stack = NSStackView(views: [spinner, message, detail])
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 10
        stack.translatesAutoresizingMaskIntoConstraints = false
        cover.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: cover.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: cover.centerYAnchor),
        ])

        content.addSubview(cover)
        window.contentView = content
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func label(_ text: String, size: CGFloat, bold: Bool) -> NSTextField {
        let f = NSTextField(labelWithString: text)
        f.font = bold ? .boldSystemFont(ofSize: size) : .systemFont(ofSize: size)
        f.alignment = .center
        return f
    }

    func show(_ text: String, detail d: String = "", spinning: Bool = true) {
        message.stringValue = text
        detail.stringValue = d
        if spinning { spinner.startAnimation(nil) } else { spinner.stopAnimation(nil) }
        spinner.isHidden = !spinning
        cover.isHidden = false
    }

    // MARK: The server

    func startServer() {
        guard let python = firstPython() else {
            show("No python3 on this Mac", detail: "Install the Xcode command line tools.",
                 spinning: false)
            return
        }
        let script = projectDir + "/server.py"
        guard FileManager.default.fileExists(atPath: script) else {
            show("Beam is not where the app expects", detail: script, spinning: false)
            return
        }

        reclaimPort(8080)   // take 8080 back from a leftover server

        server.executableURL = URL(fileURLWithPath: python)
        // The full path is what makes `pkill -f beam/server.py` find it.
        server.arguments = [script, "--port", "8080"]
        var env = ProcessInfo.processInfo.environment
        env["BEAM_TRUST_LOOPBACK"] = "1"          // this Mac's own window skips the PIN
        env["PYTHONUNBUFFERED"] = "1"
        server.environment = env

        let pipe = Pipe()
        server.standardOutput = pipe
        server.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            DispatchQueue.main.async { self?.readBanner(text) }
        }

        server.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                guard let self = self, !self.pageLoaded else { return }
                self.show("Beam stopped unexpectedly",
                          detail: "server.py exited with code \(proc.terminationStatus).",
                          spinning: false)
            }
        }

        do {
            try server.run()
        } catch {
            show("Could not start Beam", detail: error.localizedDescription, spinning: false)
            return
        }

        // The banner is the usual way the port arrives. If it never parses -
        // a future banner change, say - fall back to probing 8080 anyway.
        DispatchQueue.main.asyncAfter(deadline: .now() + 6) { [weak self] in
            guard let self = self, self.port == nil, self.server.isRunning else { return }
            self.found(port: 8080)
        }
    }

    /// Pull the port out of the server's own banner line, ANSI colours and all.
    func readBanner(_ chunk: String) {
        guard port == nil else { return }
        stdoutBuffer += chunk
        let pattern = "http://[0-9A-Za-z._-]+:([0-9]{2,5})/"
        guard let re = try? NSRegularExpression(pattern: pattern) else { return }
        let range = NSRange(stdoutBuffer.startIndex..., in: stdoutBuffer)
        guard let m = re.firstMatch(in: stdoutBuffer, range: range),
              let r = Range(m.range(at: 1), in: stdoutBuffer),
              let p = Int(stdoutBuffer[r]) else { return }
        found(port: p)
    }

    func found(port p: Int) {
        guard port == nil else { return }
        port = p
        show("Starting Beam...", detail: "waiting for port \(p)")
        probe()
    }

    /// Wait for the port to actually answer before pointing the window at it,
    /// so the first thing on screen is the page and never a failure.
    func probe() {
        guard let p = port else { return }
        probeTries += 1
        guard probeTries < 100 else {
            show("Beam did not answer", detail: "port \(p) never came up.", spinning: false)
            return
        }
        var req = URLRequest(url: URL(string: "http://127.0.0.1:\(p)/")!)
        req.timeoutInterval = 2
        req.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: req) { [weak self] _, response, _ in
            DispatchQueue.main.async {
                guard let self = self else { return }
                if response is HTTPURLResponse {
                    self.web.load(URLRequest(url: URL(string: "http://127.0.0.1:\(p)/")!))
                } else {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { self.probe() }
                }
            }
        }.resume()
    }


    /// A plain `kill` of the app would otherwise leave server.py running and
    /// the port held. AppKit does not route signals through applicationWill
    /// Terminate, so they are caught here.
    func catchSignals() {
        for sig in [SIGTERM, SIGINT, SIGHUP] {
            signal(sig, SIG_IGN)
            let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
            src.setEventHandler { [weak self] in
                self?.stopServer()
                exit(0)
            }
            src.resume()
            signalSources.append(src)
        }
    }

    func stopServer() {
        guard server.isRunning else { return }
        server.terminate()
        // Give it a moment to put its socket down cleanly.
        let deadline = Date().addingTimeInterval(3)
        while server.isRunning && Date() < deadline {
            usleep(50_000)
        }
        if server.isRunning { kill(server.processIdentifier, SIGKILL) }
    }

    // MARK: Web view

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        pageLoaded = true
        spinner.stopAnimation(nil)
        cover.isHidden = true
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        if !pageLoaded { DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self.probe() } }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        if !pageLoaded { DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self.probe() } }
    }

    /// Anything the window cannot display itself - and anything the server marks
    /// as an attachment, which is what the page's download button sends - is
    /// handed to a real download rather than dropped on the floor.
    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if let http = navigationResponse.response as? HTTPURLResponse,
           let cd = http.value(forHTTPHeaderField: "Content-Disposition"),
           cd.lowercased().contains("attachment") {
            decisionHandler(.download); return
        }
        decisionHandler(navigationResponse.canShowMIMEType ? .allow : .download)
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction,
                 didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse,
                 didBecome download: WKDownload) {
        download.delegate = self
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String,
                  completionHandler: @escaping (URL?) -> Void) {
        let dir = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
        let name = suggestedFilename.isEmpty ? "download" : suggestedFilename
        completionHandler(freeName(in: dir, for: name))
    }

    /// `movie.mkv` becomes `movie (2).mkv` rather than landing on top of
    /// something already in Downloads - the same rule the server uses.
    func freeName(in dir: URL, for name: String) -> URL {
        let base = (name as NSString).deletingPathExtension
        let ext = (name as NSString).pathExtension
        var candidate = dir.appendingPathComponent(name)
        var n = 2
        while FileManager.default.fileExists(atPath: candidate.path) {
            let next = ext.isEmpty ? "\(base) (\(n))" : "\(base) (\(n)).\(ext)"
            candidate = dir.appendingPathComponent(next)
            n += 1
        }
        return candidate
    }

    func download(_ download: WKDownload, didFailWithError error: Error,
                  resumeData: Data?) {
        NSSound.beep()
    }

    func downloadDidFinish(_ download: WKDownload) {
        if let url = download.progress.fileURL {
            NSWorkspace.shared.activateFileViewerSelecting([url])
        }
    }

    /// target=_blank (the share-link button) opens in the same window.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction,
                 windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url { webView.load(URLRequest(url: url)) }
        return nil
    }

    /// WKWebView does not show a file picker for `<input type=file>` on its own -
    /// without this delegate method, clicking "Send files" (or "Send a folder")
    /// does nothing at all, with no error either. `canChooseDirectories` also
    /// covers the folder input, since WebKit does not say here which kind of
    /// input asked.
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseFiles = true
        panel.canChooseDirectories = true
        panel.begin { response in
            completionHandler(response == .OK ? panel.urls : nil)
        }
    }

    // MARK: Menu

    @objc func reload(_ sender: Any?) { web.reload() }

    @objc func openInBrowser(_ sender: Any?) {
        guard let p = port else { return }
        NSWorkspace.shared.open(URL(string: "http://127.0.0.1:\(p)/")!)
    }

    @objc func revealDrop(_ sender: Any?) {
        let drop = ("~/Drop" as NSString).expandingTildeInPath
        NSWorkspace.shared.open(URL(fileURLWithPath: drop))
    }

    func buildMenu() {
        let main = NSMenu()

        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Beam", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Open the Drop folder", action: #selector(revealDrop(_:)), keyEquivalent: "d")
        appMenu.addItem(withTitle: "Open in browser", action: #selector(openInBrowser(_:)), keyEquivalent: "b")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Beam", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Beam", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)

        // Without an Edit menu the standard shortcuts are dead, and the page
        // leans on paste: Cmd-V drops a file straight into the folder.
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)

        let viewItem = NSMenuItem()
        let view = NSMenu(title: "View")
        view.addItem(withTitle: "Reload", action: #selector(reload(_:)), keyEquivalent: "r")
        viewItem.submenu = view
        main.addItem(viewItem)

        let windowItem = NSMenuItem()
        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(withTitle: "Minimise", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        windowMenu.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        windowItem.submenu = windowMenu
        main.addItem(windowItem)

        NSApp.mainMenu = main
        NSApp.windowsMenu = windowMenu
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
