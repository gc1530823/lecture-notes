import PDFKit
import SwiftUI

/// 강의 정리 PDF: 필기가 붙은 슬라이드 + 페이지별 전체 정리 + 교수님 설명 + 과제.
/// 열 때마다 지금까지의 필기로 서버에 새로 만들게 하고(바뀌지 않은 페이지는 서버가 전에 만든 정리를 쓴다),
/// 다 되면 앱 안에서 미리 보고 공유 버튼으로 파일·굿노트 등에 저장한다.
struct NotesPDFView: View {
    let sessionID: String
    let title: String

    @Environment(\.dismiss) private var dismiss
    @State private var progress: NotesPDFStatus?
    @State private var fileURL: URL?
    @State private var errorMessage: String?

    /// initialProgress가 있으면(데모 모드) 서버에 묻지 않고 그 진행 상태를 보여 준다.
    init(sessionID: String, title: String, initialProgress: NotesPDFStatus? = nil) {
        self.sessionID = sessionID
        self.title = title
        _progress = State(initialValue: initialProgress)
    }

    var body: some View {
        NavigationStack {
            Group {
                if let fileURL {
                    PDFPreview(url: fileURL)
                        .ignoresSafeArea(edges: .bottom)
                } else if let errorMessage {
                    ContentUnavailableView {
                        Label("PDF를 만들지 못했어요", systemImage: "exclamationmark.triangle")
                    } description: {
                        Text(errorMessage)
                    } actions: {
                        Button("다시 만들기") { Task { await build() } }
                            .buttonStyle(.borderedProminent)
                    }
                } else {
                    BuildingView(progress: progress)
                }
            }
            .background(Theme.paper.ignoresSafeArea())
            .navigationTitle("강의 정리 PDF")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } }
                if let fileURL {
                    ToolbarItem(placement: .primaryAction) {
                        ShareLink(item: fileURL) { Image(systemName: "square.and.arrow.up") }
                    }
                }
            }
        }
        .tint(Theme.accent)
        .fontDesign(.rounded)
        .task { if progress == nil { await build() } }
    }

    private func build() async {
        errorMessage = nil
        do {
            let api = try APIClient.current()
            var status = try await api.startNotesPDF(sessionId: sessionID)
            while status.status == "building" {
                progress = status
                try await Task.sleep(for: .seconds(2))
                status = try await api.notesPDFStatus(sessionId: sessionID)
            }
            guard status.status == "ready" else {
                errorMessage = "잠시 뒤 다시 눌러 주세요."
                return
            }
            fileURL = try await api.downloadNotesPDF(sessionId: sessionID, title: title)
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct BuildingView: View {
    let progress: NotesPDFStatus?

    var body: some View {
        VStack(spacing: 22) {
            ZStack(alignment: .topTrailing) {
                Image(systemName: "doc.richtext.fill")
                    .font(.system(size: 64))
                    .foregroundStyle(Theme.accent)
                    .symbolEffect(.pulse)
                FoldedPaper(fold: 8)
                    .fill(AnnotationType.exam.noteColor)
                    .frame(width: 30, height: 30)
                    .rotationEffect(.degrees(8))
                    .offset(x: 14, y: -8)
                    .shadow(color: .black.opacity(0.12), radius: 2, y: 1)
            }
            VStack(spacing: 8) {
                Text("AI가 페이지별로 정리하는 중…")
                    .font(.headline)
                Text("필기가 붙은 슬라이드와 교수님 설명을 빠짐없이 정리한 노트, 과제를 한 권으로 만들어요")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            if let progress, progress.total > 0 {
                VStack(spacing: 6) {
                    ProgressView(value: Double(progress.done), total: Double(progress.total))
                    Text("\(progress.done) / \(progress.total)쪽")
                        .font(.caption.weight(.semibold).monospacedDigit())
                        .foregroundStyle(.secondary)
                        .contentTransition(.numericText())
                }
                .frame(maxWidth: 240)
                .animation(.snappy, value: progress.done)
            } else {
                ProgressView()
            }
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct PDFPreview: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> PDFView {
        let view = PDFView()
        view.autoScales = true
        view.displayMode = .singlePageContinuous
        view.backgroundColor = .secondarySystemBackground
        view.document = PDFDocument(url: url)
        return view
    }

    func updateUIView(_ view: PDFView, context: Context) {
        if view.document?.documentURL != url { view.document = PDFDocument(url: url) }
    }
}
