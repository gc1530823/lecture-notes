import SwiftUI

@main
struct LectureNotesApp: App {
    @StateObject private var store = DocumentStore(demo: DemoScreen.current?.usesDemoDocuments ?? false)

    var body: some Scene {
        WindowGroup {
            Group {
                if let demo = DemoScreen.current {
                    DemoRootView(screen: demo)
                } else {
                    DocumentListView()
                }
            }
            .environmentObject(store)
            .tint(Theme.accent)
            .fontDesign(.rounded)
        }
    }
}
