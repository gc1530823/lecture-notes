import SwiftUI

@main
struct LectureNotesApp: App {
    @StateObject private var store = DocumentStore(demo: DemoScreen.current != nil)

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
        }
    }
}
