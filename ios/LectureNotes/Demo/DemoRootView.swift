import SwiftUI

/// `-demoScreen <이름>` 실행 인자로 고르는 데모 화면
enum DemoScreen: String {
    case empty, list, detail, lecture, recording, live, summary

    static var current: DemoScreen? {
        let arguments = ProcessInfo.processInfo.arguments
        guard let index = arguments.firstIndex(of: "-demoScreen"), index + 1 < arguments.count else { return nil }
        return DemoScreen(rawValue: arguments[index + 1])
    }

    /// 예시 강의자료를 채울지 (empty는 빈 목록 화면)
    var usesDemoDocuments: Bool { self != .empty }
}

struct DemoRootView: View {
    @EnvironmentObject private var store: DocumentStore
    let screen: DemoScreen

    var body: some View {
        switch screen {
        case .empty, .list:
            DocumentListView()
        case .detail:
            NavigationStack { DocumentDetailView(documentID: DemoData.document.id) }
        case .lecture, .recording, .live:
            NavigationStack {
                LectureView(document: DemoData.document, store: store,
                            session: screen == .lecture ? DemoData.document.sessions.first : nil, demo: screen)
            }
        case .summary:
            SummaryView(sessionID: DemoData.sessionID, initialSummary: DemoData.summary, onSelectPage: { _ in })
        }
    }
}

#Preview("자료 목록") { DemoRootView(screen: .list).environmentObject(DocumentStore(demo: true)) }
#Preview("강의 화면") { DemoRootView(screen: .lecture).environmentObject(DocumentStore(demo: true)) }
#Preview("실시간 필기") { DemoRootView(screen: .live).environmentObject(DocumentStore(demo: true)) }
#Preview("요약·퀴즈") { DemoRootView(screen: .summary).environmentObject(DocumentStore(demo: true)) }
