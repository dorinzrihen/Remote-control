import AppKit
import Foundation

// A real, long-lived GUI application gives Local Network Privacy a stable
// responsible-app identity. The Python child remains the only bulb controller.
final class LightsApplication: NSObject, NSApplicationDelegate {
    private var manager: Process?
    private var quitting = false
    private var output: FileHandle?

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            let home = FileManager.default.homeDirectoryForCurrentUser
            let logURL = home.appendingPathComponent("Library/Logs/com.uniremote.wiz.log")
            try FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            if !FileManager.default.fileExists(atPath: logURL.path) {
                FileManager.default.createFile(atPath: logURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
            }
            let handle = try FileHandle(forWritingTo: logURL)
            try handle.seekToEnd()
            output = handle
            guard let script = Bundle.main.object(forInfoDictionaryKey: "ButlerManagerScript") as? String,
                  FileManager.default.fileExists(atPath: script) else {
                throw NSError(domain: "ButlerLights", code: 1, userInfo: [NSLocalizedDescriptionKey: "Manager script is missing; reinstall the launcher with the correct repository path."])
            }
            let child = Process()
            child.executableURL = URL(fileURLWithPath: "/bin/sh")
            child.arguments = [script]
            child.currentDirectoryURL = URL(fileURLWithPath: script).deletingLastPathComponent()
            var environment = ProcessInfo.processInfo.environment
            environment["HOME"] = home.path
            environment["PATH"] = "\(home.path)/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            child.environment = environment
            child.standardOutput = handle
            child.standardError = handle
            child.terminationHandler = { [weak self] process in
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    self.log("Manager exited with status \(process.terminationStatus)")
                    if self.quitting {
                        NSApp.reply(toApplicationShouldTerminate: true)
                    } else {
                        NSApp.terminate(nil)
                    }
                }
            }
            manager = child
            try child.run()
            log("Mac app started manager PID \(child.processIdentifier)")
        } catch {
            let alert = NSAlert()
            alert.messageText = "Butler Lights could not start"
            alert.informativeText = error.localizedDescription
            alert.runModal()
            NSApp.terminate(nil)
        }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let child = manager, child.isRunning else { return .terminateNow }
        quitting = true
        child.terminate()
        return .terminateLater
    }

    private func log(_ message: String) {
        guard let data = "\(ISO8601DateFormatter().string(from: Date())) \(message)\n".data(using: .utf8) else { return }
        try? output?.write(contentsOf: data)
    }
}

let application = NSApplication.shared
let delegate = LightsApplication()
application.delegate = delegate
application.setActivationPolicy(.accessory)
// Graceful service unload also reaps the Python child; don't leave an orphan.
signal(SIGTERM, SIG_IGN)
let terminationSignal = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
terminationSignal.setEventHandler { application.terminate(nil) }
terminationSignal.resume()
application.run()
