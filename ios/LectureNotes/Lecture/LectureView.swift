import PDFKit
import SwiftUI

/// 강의 화면: 위에는 강의자료 페이지와 필기 위치, 아래에는 그 페이지의 필기 목록.
struct LectureView: View {
    @StateObject private var model: LectureViewModel
    @State private var selectedAnnotationID: Int?
    @State private var editing: Annotation?
    @State private var showingSummary = false

    private let demoSummary: LectureSummary?

    init(document: LocalDocument, store: DocumentStore, session: SavedSession?, demo: DemoScreen? = nil) {
        let model = LectureViewModel(document: document, store: store, existingSession: session)
        switch demo {
        case .lecture:
            model.applyDemo(annotations: DemoData.annotations, phase: .ended, caption: nil)
        case .recording:
            model.applyDemo(annotations: Array(DemoData.annotations.prefix(3)), phase: .recording,
                            caption: "그래서 학습률은 보통 0.01이나 0.001부터 시작해서 줄여 가요")
        default:
            break
        }
        _model = StateObject(wrappedValue: model)
        demoSummary = demo == nil ? nil : DemoData.summary
    }

    var body: some View {
        VStack(spacing: 0) {
            TabView(selection: $model.currentPage) {
                ForEach(model.pages) { page in
                    PageCanvasView(
                        page: page,
                        pdfPage: model.pdf?.page(at: page.pageNo - 1),
                        annotations: model.annotations(onPage: page.pageNo),
                        selectedAnnotationID: $selectedAnnotationID
                    )
                    .padding(.horizontal, 12)
                    .tag(page.pageNo)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            .frame(maxHeight: .infinity)
            .layoutPriority(1)

            if model.phase == .recording {
                CaptionBar(recorder: model.recorder)
            }

            AnnotationListView(
                annotations: model.annotations(onPage: model.currentPage),
                latestID: model.latestAnnotationID,
                selectedID: $selectedAnnotationID,
                onEdit: { editing = $0 },
                onDelete: { annotation in Task { await model.delete(annotation) } }
            )
            .frame(maxHeight: .infinity)

            bottomBar
        }
        .navigationTitle(model.document.document.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if model.phase == .ended, model.session != nil {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("요약·퀴즈") { showingSummary = true }
                }
            }
        }
        .sheet(item: $editing) { annotation in
            AnnotationEditSheet(annotation: annotation) { text in
                Task { await model.update(annotation, text: text) }
            }
        }
        .sheet(isPresented: $showingSummary) {
            if let session = model.session {
                SummaryView(sessionID: session.id, initialSummary: demoSummary, onSelectPage: { page in
                    model.currentPage = page
                    showingSummary = false
                })
            }
        }
        .alert("알림", isPresented: .constant(model.errorMessage != nil)) {
            Button("확인") { model.errorMessage = nil }
        } message: {
            Text(model.errorMessage ?? "")
        }
        .task { if demoSummary == nil { await model.loadExistingAnnotations() } }
        .onDisappear { model.leave() }
        .navigationBarBackButtonHidden(model.phase == .recording || model.phase == .finishing)
    }

    private var bottomBar: some View {
        HStack {
            Text("\(model.currentPage) / \(model.pages.count)")
                .font(.subheadline.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 72, alignment: .leading)
            Spacer()
            recordButton
            Spacer()
            ElapsedLabel(recorder: model.recorder)
                .frame(width: 72, alignment: .trailing)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.bar)
    }

    @ViewBuilder
    private var recordButton: some View {
        switch model.phase {
        case .ready:
            Button { Task { await model.startLecture() } } label: {
                Label("녹음 시작", systemImage: "mic.fill")
            }
            .buttonStyle(.borderedProminent)
            .tint(.red)
        case .recording:
            Button { Task { await model.stopLecture() } } label: {
                Label("강의 끝내기", systemImage: "stop.fill")
            }
            .buttonStyle(.bordered)
            .tint(.red)
        case .finishing:
            ProgressView("마무리 중…")
        case .ended:
            Button { showingSummary = true } label: {
                Label("요약·퀴즈 보기", systemImage: "list.bullet.rectangle")
            }
            .buttonStyle(.borderedProminent)
        }
    }
}

/// 지금 인식 중인 말(아직 확정 전)을 자막처럼 보여 준다.
private struct CaptionBar: View {
    @ObservedObject var recorder: SpeechRecorder

    var body: some View {
        HStack(spacing: 8) {
            Circle().fill(.red).frame(width: 8, height: 8)
            Text(recorder.partialText.isEmpty ? "듣고 있어요…" : recorder.partialText)
                .font(.footnote)
                .lineLimit(2)
                .foregroundStyle(recorder.partialText.isEmpty ? .secondary : .primary)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .background(Color(.secondarySystemBackground))
    }
}

private struct ElapsedLabel: View {
    @ObservedObject var recorder: SpeechRecorder

    var body: some View {
        let seconds = Int(recorder.elapsed)
        Text(String(format: "%02d:%02d", seconds / 60, seconds % 60))
            .font(.subheadline.monospacedDigit())
            .foregroundStyle(recorder.isRecording ? .red : .secondary)
    }
}
