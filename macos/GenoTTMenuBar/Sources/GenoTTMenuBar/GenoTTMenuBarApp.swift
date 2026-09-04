import AppKit
import SwiftUI

@main
struct GenoTTMenuBarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        MenuBarExtra("Geno TT", systemImage: "terminal") {
            VStack(alignment: .leading, spacing: 12) {
                Label("Geno TT", systemImage: "terminal")
                    .font(.headline)

                Text("Workspace controls are coming soon.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                Divider()

                Button("Quit Geno TT") {
                    NSApplication.shared.terminate(nil)
                }
                .keyboardShortcut("q")
            }
            .padding()
            .frame(width: 260)
        }
        .menuBarExtraStyle(.window)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApplication.shared.setActivationPolicy(.accessory)
    }
}
