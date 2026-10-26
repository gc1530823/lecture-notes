import SwiftUI

@main
struct LectureNotesApp: App {
    @StateObject private var store = DocumentStore()

    var body: some Scene {
        WindowGroup {
            DocumentListView()
                .environmentObject(store)
        }
    }
}
