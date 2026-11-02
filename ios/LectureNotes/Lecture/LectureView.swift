import PDFKit
import SwiftUI

/// 강의 화면: 위에는 강의자료 페이지(형광펜 + 깃발), 아래에는 그 페이지의 포스트잇 필기.
struct LectureView: View {
    @StateObject private var model: LectureViewModel
    @State private var selectedAnnotationID: Int?
    @State private var editing: Annotation?
    @State private var showingSummary = false
    @State private var showingNotesPDF = false
    @State private var showingAsk = false
    @State private var asking = false
    @State private var showingPending = false
    @State private var showingTasks = false
    @State private var openTask: LectureTask?
    /// 방금 들어온 필기를 자료 위에 잠깐 펼쳐 보여 준다
    @State private var freshAnnotationID: Int?
    private let demo: DemoScreen?

    init(document: LocalDocument, store: DocumentStore, session: SavedSession?, demo: DemoScreen? = nil) {
        // StateObject의 값은 화면이 처음 나타날 때 한 번만 만든다 (NavigationLink 목적지는 미리 init되므로)
        _model = StateObject(wrappedValue: Self.makeModel(document: document, store: store, session: session, demo: demo))
        self.demo = demo
        // 데모 강의 화면은 3번 필기를 펼친 상태로 보여 준다
        _selectedAnnotationID = State(initialValue: demo == .lecture ? 3 : nil)
        _showingNotesPDF = State(initialValue: demo == .notesPDF)
        _showingAsk = State(initialValue: demo == .ask)
    }

    private static func makeModel(document: LocalDocument, store: DocumentStore, session: SavedSession?,
                                  demo: DemoScreen?) -> LectureViewModel {
        let model = LectureViewModel(document: document, store: store, existingSession: session)
        switch demo {
        case .lecture, .notesPDF, .ask:
            model.applyDemo(annotations: DemoData.annotations, phase: .ended, caption: nil, tasks: DemoData.tasks)
        case .recording:
            model.applyDemo(annotations: Array(DemoData.annotations.prefix(3)), phase: .recording,
                            caption: "그래서 학습률은 보통 0.01이나 0.001부터 시작해서 줄여 가요",
                            tasks: [DemoData.tasks[0]])
            model.freshTask = DemoData.tasks[0]
        case .task:
            var drafted = DemoData.tasks[0]
            drafted.draft = DemoData.draft
            model.applyDemo(annotations: DemoData.annotations, phase: .ended, caption: nil,
                            tasks: [drafted, DemoData.tasks[1]])
        case .live:
            model.applyDemo(annotations: [], phase: .recording, caption: "")
        default:
            break
        }
        return model
    }

    var body: some View {
        GeometryReader { proxy in
            content(pageHeight: pageAreaHeight(width: proxy.size.width, available: proxy.size.height))
        }
        .background(Theme.paper.ignoresSafeArea())
        .navigationTitle(model.document.document.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(Theme.paper, for: .navigationBar)
        .toolbar {
            // 정리 PDF는 녹음 중에도 지금까지의 필기로 만들 수 있다
            if model.session != nil {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showingNotesPDF = true } label: { Image(systemName: "doc.richtext") }
                        .accessibilityLabel("강의 정리 PDF")
                }
            }
            if model.phase == .ended, model.session != nil {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showingSummary = true } label: { Image(systemName: "sparkles.rectangle.stack") }
                }
            }
        }
        .sheet(isPresented: $showingAsk) {
            AskSheet(pageNo: model.currentPage) { question in
                showingAsk = false
                asking = true
                Task {
                    await model.ask(question)
                    asking = false
                }
            }
            .presentationDetents([.height(340)])
        }
        .sheet(isPresented: $showingNotesPDF) {
            if let session = model.session {
                NotesPDFView(sessionID: session.id, title: model.document.document.title,
                             initialProgress: demo == .notesPDF ? NotesPDFStatus(status: "building", done: 3, total: 5) : nil)
            }
        }
        .sheet(item: $editing) { annotation in
            AnnotationEditSheet(annotation: annotation) { text in
                Task { await model.update(annotation, text: text) }
            }
        }
        .overlay(alignment: .top) {
            if let task = model.freshTask {
                TaskBanner(task: task, onOpen: {
                    openTask = task
                    showingTasks = true
                    withAnimation(.snappy) { model.freshTask = nil }
                }, onClose: {
                    withAnimation(.snappy) { model.freshTask = nil }
                })
                .padding(.top, 6)
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.5, dampingFraction: 0.8), value: model.freshTask)
        .task(id: model.freshTask?.id) {
            // 데모 스크린샷용 배너는 그대로 두고, 실제로는 8초 뒤 접는다
            guard model.freshTask != nil, demo != .recording else { return }
            try? await Task.sleep(for: .seconds(8))
            guard !Task.isCancelled else { return }
            withAnimation(.snappy) { model.freshTask = nil }
        }
        .sheet(isPresented: $showingTasks, onDismiss: { openTask = nil }) {
            TasksSheet(model: model, startWith: openTask)
        }
        .sheet(isPresented: $showingPending) {
            PendingTraySheet(model: model)
        }
        .sheet(isPresented: $showingSummary) {
            if let session = model.session {
                SummaryView(sessionID: session.id, initialSummary: demo == nil ? nil : DemoData.summary,
                            onSelectPage: { page in
                                model.currentPage = page
                                showingSummary = false
                            })
            }
        }
        .onDisappear { model.player.stop() }
        .alert("알림", isPresented: .constant(model.errorMessage != nil)) {
            Button("확인") { model.errorMessage = nil }
        } message: {
            Text(model.errorMessage ?? "")
        }
        .task {
            if demo == .live {
                await model.runDemoLive()
            } else if demo == nil {
                await model.loadExistingAnnotations()
            }
        }
        .sensoryFeedback(.impact(weight: .light), trigger: model.annotations.count)
        .task(id: model.latestAnnotationID) {
            // 새 필기는 5초 동안 자료 위에 펼쳐 두었다가 깃발로 접는다
            guard let id = model.latestAnnotationID else { return }
            withAnimation(.spring(response: 0.45, dampingFraction: 0.72)) { freshAnnotationID = id }
            try? await Task.sleep(for: .seconds(5))
            guard !Task.isCancelled else { return }
            withAnimation(.easeInOut(duration: 0.3)) { freshAnnotationID = nil }
        }
        .onDisappear { model.leave() }
        .navigationBarBackButtonHidden(model.phase == .recording || model.phase == .finishing)
    }

    /// 페이지는 화면 너비에 맞춘 높이만 차지하고 (최대 화면의 절반), 나머지는 필기 보드에 준다.
    private func pageAreaHeight(width: CGFloat, available: CGFloat) -> CGFloat {
        let aspect = model.pages.first?.aspectRatio ?? 16 / 9
        return min((width - 32) / aspect + 28, available * 0.48)
    }

    private func content(pageHeight: CGFloat) -> some View {
        let pageAnnotations = model.annotations(onPage: model.currentPage)
        return VStack(spacing: 0) {
            TabView(selection: $model.currentPage) {
                ForEach(model.pages) { page in
                    PageCanvasView(
                        page: page,
                        pdfPage: model.pdf?.page(at: page.pageNo - 1),
                        annotations: model.annotations(onPage: page.pageNo),
                        selectedAnnotationID: $selectedAnnotationID,
                        spotlightID: selectedAnnotationID ?? freshAnnotationID
                    )
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .tag(page.pageNo)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            .frame(height: pageHeight)

            boardHeader(count: pageAnnotations.count)

            AnnotationBoardView(
                annotations: pageAnnotations,
                latestID: model.latestAnnotationID,
                isRecording: model.phase == .recording,
                selectedID: $selectedAnnotationID,
                onEdit: { editing = $0 },
                onDelete: { annotation in Task { await model.delete(annotation) } },
                canPlay: model.canPlayRecording,
                onPlay: { model.playRecording(at: $0) }
            )
            .frame(maxHeight: .infinity)
            .safeAreaInset(edge: .bottom) {
                VStack(spacing: 10) {
                    PlayerBar(player: model.player)
                    if model.session != nil {
                        AskButton(asking: asking) { showingAsk = true }
                            .frame(maxWidth: .infinity, alignment: .trailing)
                    }
                    if model.phase == .recording {
                        CaptionPill(recorder: model.recorder)
                            .transition(.move(edge: .bottom).combined(with: .opacity))
                    }
                    controlBar
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 6)
                .animation(.spring(response: 0.45, dampingFraction: 0.8), value: model.phase)
            }
        }
    }

    private func boardHeader(count: Int) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text("\(model.currentPage)쪽 필기")
                .font(.system(.headline, design: .rounded).weight(.bold))
                .contentTransition(.numericText())
            Text("\(count)")
                .font(.system(.subheadline, design: .rounded).weight(.heavy))
                .foregroundStyle(Theme.accent)
                .contentTransition(.numericText())
            Spacer()
            if !model.tasks.isEmpty {
                Button { showingTasks = true } label: {
                    Label("과제 \(model.tasks.filter { !$0.done }.count)", systemImage: "checklist")
                        .font(.caption.weight(.heavy))
                        .foregroundStyle(Theme.record)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 5)
                        .background(Theme.record.opacity(0.12), in: Capsule())
                        .contentTransition(.numericText())
                }
                .buttonStyle(PressableStyle(scale: 0.9))
                .transition(.scale.combined(with: .opacity))
            }
            if !model.pendingAnnotations.isEmpty {
                Button { showingPending = true } label: {
                    Label("보류 \(model.pendingAnnotations.count)", systemImage: "tray.full.fill")
                        .font(.caption.weight(.heavy))
                        .foregroundStyle(.orange)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 5)
                        .background(Color.orange.opacity(0.14), in: Capsule())
                        .contentTransition(.numericText())
                }
                .buttonStyle(PressableStyle(scale: 0.9))
                .transition(.scale.combined(with: .opacity))
            }
            if model.phase == .recording {
                AutoFollowChip(isOn: $model.autoFollow, estimatedPage: model.estimatedPage,
                               currentPage: model.currentPage)
            } else {
                PageDots(count: model.pages.count, current: model.currentPage)
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 6)
        .animation(.spring(response: 0.4, dampingFraction: 0.75), value: model.pendingAnnotations.count)
        .animation(.spring(response: 0.4, dampingFraction: 0.75), value: model.tasks.count)
        .animation(.snappy, value: count)
        .animation(.snappy, value: model.currentPage)
    }

    // 아래 떠 있는 조작 막대: 페이지 이동 · 녹음 버튼 · 시간과 파형

    private var controlBar: some View {
        HStack(spacing: 12) {
            HStack(spacing: 2) {
                pageStepButton("chevron.left", to: model.currentPage - 1)
                Text("\(model.currentPage)/\(model.pages.count)")
                    .font(.system(.footnote, design: .rounded).weight(.bold).monospacedDigit())
                    .contentTransition(.numericText())
                    .frame(minWidth: 34)
                pageStepButton("chevron.right", to: model.currentPage + 1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            mainButton

            RecordingStatus(recorder: model.recorder)
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(.ultraThinMaterial, in: Capsule())
        .overlay(Capsule().strokeBorder(.white.opacity(0.4)))
        .shadow(color: .black.opacity(0.12), radius: 16, y: 6)
    }

    private func pageStepButton(_ symbol: String, to page: Int) -> some View {
        Button {
            withAnimation(.snappy) { model.currentPage = page }
        } label: {
            Image(systemName: symbol)
                .font(.footnote.weight(.bold))
                .frame(width: 28, height: 28)
        }
        .disabled(page < 1 || page > model.pages.count)
        .buttonStyle(PressableStyle(scale: 0.85))
    }

    @ViewBuilder
    private var mainButton: some View {
        switch model.phase {
        case .ready:
            RecordButton(isRecording: false) { Task { await model.startLecture() } }
        case .recording:
            RecordButton(isRecording: true) { Task { await model.stopLecture() } }
        case .finishing:
            ProgressView()
                .controlSize(.large)
                .frame(width: 62, height: 62)
        case .ended:
            Button { showingSummary = true } label: {
                Label("요약·퀴즈", systemImage: "sparkles")
                    .font(.system(.subheadline, design: .rounded).weight(.bold))
                    .lineLimit(1)
                    .fixedSize()
                    .foregroundStyle(.white)
                    .padding(.horizontal, 18)
                    .frame(height: 48)
                    .background(Theme.accent.gradient, in: Capsule())
                    .shadow(color: Theme.accent.opacity(0.4), radius: 8, y: 4)
            }
            .buttonStyle(PressableStyle())
        }
    }
}

/// 녹음 시작·끝 버튼. 녹음 중에는 빨간 원이 숨 쉬듯 퍼진다.
/// 필기에서 연 녹음 재생 막대
private struct PlayerBar: View {
    @ObservedObject var player: LecturePlayer

    var body: some View {
        if player.isActive {
            HStack(spacing: 12) {
                Button { player.togglePause() } label: {
                    Image(systemName: player.isPlaying ? "pause.fill" : "play.fill").font(.title3)
                }
                Text(player.currentMs.clockText)
                    .font(.subheadline.weight(.heavy).monospacedDigit())
                    .frame(minWidth: 44, alignment: .leading)
                Slider(value: Binding(
                    get: { player.durationMs > 0 ? Double(player.currentMs) / Double(player.durationMs) : 0 },
                    set: { player.seek(toFraction: $0) }))
                Button { player.stop() } label: { Image(systemName: "xmark").font(.subheadline.weight(.bold)) }
            }
            .tint(Theme.accent)
            .foregroundStyle(Theme.accent)
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(.regularMaterial, in: Capsule())
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }
}

/// "방금 뭐라고?" 버튼. 답을 기다리는 동안은 돌아가는 표시를 보여 준다.
private struct AskButton: View {
    let asking: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if asking {
                    ProgressView().tint(.white)
                    Text("답을 찾는 중…")
                } else {
                    Image(systemName: "hand.raised.fill")
                    Text("방금 뭐라고?")
                }
            }
            .font(.subheadline.weight(.heavy))
            .foregroundStyle(.white)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(AnnotationType.qa.inkColor.gradient, in: Capsule())
            .shadow(color: AnnotationType.qa.inkColor.opacity(0.35), radius: 8, y: 4)
        }
        .buttonStyle(PressableStyle(scale: 0.95))
        .disabled(asking)
        .sensoryFeedback(.impact(weight: .light), trigger: asking)
    }
}

/// 질문 고르기·적기. 비워서 보내면 서버가 "방금 설명 다시"로 묻는다.
private struct AskSheet: View {
    let pageNo: Int
    let onAsk: (String) -> Void
    @State private var question = ""
    private let quick = ["방금 뭐라고 했어?", "쉽게 다시 설명해 줘", "예시 하나만 들어 줘", "이거 시험에 어떻게 나올까?"]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("방금 뭐라고?", systemImage: "hand.raised.fill")
                .font(.title3.weight(.bold))
                .foregroundStyle(AnnotationType.qa.inkColor)
            Text("최근 2분 동안의 설명과 \(pageNo)쪽 자료를 보고 답해서, 관련 문단 옆에 붙여 줘요.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            FlowChips(items: quick) { onAsk($0) }
            HStack(spacing: 10) {
                TextField("궁금한 걸 적어도 돼요", text: $question)
                    .textFieldStyle(.roundedBorder)
                    .submitLabel(.send)
                    .onSubmit { onAsk(question) }
                Button("묻기") { onAsk(question) }
                    .buttonStyle(.borderedProminent)
                    .tint(AnnotationType.qa.inkColor)
            }
        }
        .padding(20)
        .frame(maxHeight: .infinity, alignment: .top)
        .fontDesign(.rounded)
    }
}

/// 빠른 질문 칩 두 줄
private struct FlowChips: View {
    let items: [String]
    let onTap: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(stride(from: 0, to: items.count, by: 2)), id: \.self) { start in
                HStack(spacing: 8) {
                    ForEach(items[start..<min(start + 2, items.count)], id: \.self) { item in
                        Button { onTap(item) } label: {
                            Text(item)
                                .font(.footnote.weight(.bold))
                                .foregroundStyle(AnnotationType.qa.inkColor)
                                .padding(.horizontal, 12)
                                .padding(.vertical, 8)
                                .background(AnnotationType.qa.inkColor.opacity(0.12), in: Capsule())
                        }
                        .buttonStyle(PressableStyle(scale: 0.95))
                    }
                }
            }
        }
    }
}

private struct RecordButton: View {
    let isRecording: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                if isRecording {
                    Circle()
                        .fill(Theme.record.opacity(0.25))
                        .phaseAnimator([false, true]) { ring, expanded in
                            ring.scaleEffect(expanded ? 1.35 : 1).opacity(expanded ? 0 : 0.9)
                        } animation: { _ in .easeOut(duration: 1.4) }
                }
                Circle()
                    .fill(Theme.record.gradient)
                    .shadow(color: Theme.record.opacity(0.45), radius: 10, y: 4)
                Group {
                    if isRecording {
                        RoundedRectangle(cornerRadius: 5).fill(.white).frame(width: 20, height: 20)
                    } else {
                        Image(systemName: "mic.fill").font(.title2.weight(.semibold)).foregroundStyle(.white)
                    }
                }
                .transition(.scale.combined(with: .opacity))
            }
            .frame(width: 62, height: 62)
            .animation(.spring(response: 0.35, dampingFraction: 0.7), value: isRecording)
        }
        .buttonStyle(PressableStyle(scale: 0.9))
        .sensoryFeedback(.impact(weight: .medium), trigger: isRecording)
        .accessibilityLabel(isRecording ? "강의 끝내기" : "녹음 시작")
    }
}

/// 녹음 시간 + 소리 크기 파형
private struct RecordingStatus: View {
    @ObservedObject var recorder: SpeechRecorder

    var body: some View {
        let seconds = Int(recorder.elapsed)
        HStack(spacing: 8) {
            if recorder.isRecording {
                Waveform(level: recorder.level)
                    .frame(width: 26, height: 22)
                    .transition(.scale.combined(with: .opacity))
            }
            Text(String(format: "%02d:%02d", seconds / 60, seconds % 60))
                .font(.system(.footnote, design: .rounded).weight(.bold).monospacedDigit())
                .foregroundStyle(recorder.isRecording ? Theme.record : .secondary)
                .contentTransition(.numericText())
        }
        .animation(.snappy, value: recorder.isRecording)
    }
}

/// 소리 크기에 맞춰 높이가 바뀌는 막대 5개
private struct Waveform: View {
    let level: CGFloat
    private let weights: [CGFloat] = [0.45, 0.8, 1, 0.7, 0.5]

    var body: some View {
        TimelineView(.animation(minimumInterval: 0.08)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            HStack(alignment: .center, spacing: 2.5) {
                ForEach(weights.indices, id: \.self) { i in
                    let wobble = (sin(t * 9 + Double(i) * 1.3) + 1) / 2
                    Capsule()
                        .fill(Theme.record)
                        .frame(width: 3, height: max(4, 22 * weights[i] * (0.25 + level * 0.75) * (0.6 + 0.4 * wobble)))
                }
            }
            .frame(maxHeight: .infinity)
            .animation(.easeOut(duration: 0.12), value: level)
        }
    }
}

/// 지금 인식 중인 말(확정 전)을 자막처럼 보여 준다.
private struct CaptionPill: View {
    @ObservedObject var recorder: SpeechRecorder

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Circle()
                .fill(Theme.record)
                .frame(width: 8, height: 8)
                .padding(.top, 6)
                .phaseAnimator([1.0, 0.3]) { dot, opacity in dot.opacity(opacity) } animation: { _ in .easeInOut(duration: 0.8) }
            Text(recorder.partialText.isEmpty ? "듣고 있어요…" : recorder.partialText)
                .font(.system(.footnote, design: .rounded).weight(.medium))
                .foregroundStyle(recorder.partialText.isEmpty ? .secondary : .primary)
                .lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)
                .animation(.easeOut(duration: 0.15), value: recorder.partialText)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .shadow(color: .black.opacity(0.08), radius: 8, y: 3)
    }
}

/// 페이지 위치 점 (현재 페이지는 길게)
private struct PageDots: View {
    let count: Int
    let current: Int

    var body: some View {
        HStack(spacing: 4) {
            ForEach(1...max(count, 1), id: \.self) { page in
                Capsule()
                    .fill(page == current ? Theme.accent : Color.secondary.opacity(0.3))
                    .frame(width: page == current ? 16 : 6, height: 6)
            }
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.75), value: current)
    }
}

/// 자동 넘김 켜고 끄기. 끈 상태에서 교수님이 다른 페이지를 설명 중이면 알려 준다.
private struct AutoFollowChip: View {
    @Binding var isOn: Bool
    let estimatedPage: Int?
    let currentPage: Int

    var body: some View {
        Button { withAnimation(.snappy) { isOn.toggle() } } label: {
            HStack(spacing: 4) {
                Image(systemName: isOn ? "wand.and.stars" : "hand.raised.fill")
                    .symbolEffect(.bounce, value: isOn)
                if !isOn, let estimatedPage, estimatedPage != currentPage {
                    Text("지금 \(estimatedPage)쪽 설명 중")
                } else {
                    Text(isOn ? "자동 넘김" : "직접 넘김")
                }
            }
            .font(.caption.weight(.heavy))
            .foregroundStyle(isOn ? Theme.accent : .secondary)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background((isOn ? Theme.accent : Color.secondary).opacity(0.12), in: Capsule())
        }
        .buttonStyle(PressableStyle(scale: 0.9))
        .accessibilityHint("교수님이 설명하는 페이지로 화면을 자동으로 넘깁니다")
    }
}

/// 어느 페이지인지 확실하지 않은 필기를 모아 두고, 눌러서 원하는 페이지에 붙인다.
private struct PendingTraySheet: View {
    @ObservedObject var model: LectureViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Text("AI가 어느 페이지 이야기인지 확신하지 못한 필기예요. 붙일 페이지를 골라 주세요.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    ForEach(model.pendingAnnotations) { annotation in
                        VStack(alignment: .leading, spacing: 12) {
                            StickyNote(annotation: annotation, number: 0)
                            ScrollView(.horizontal) {
                                HStack(spacing: 8) {
                                    ForEach(model.pages) { page in
                                        Button {
                                            Task {
                                                await model.place(annotation, onPage: page.pageNo)
                                                if model.pendingAnnotations.isEmpty { dismiss() }
                                            }
                                        } label: {
                                            Text("\(page.pageNo)쪽에 붙이기")
                                                .font(.caption.weight(.bold))
                                                .padding(.horizontal, 12)
                                                .padding(.vertical, 8)
                                                .background(Theme.accent.opacity(page.pageNo == annotation.pageNo ? 0.2 : 0.08),
                                                            in: Capsule())
                                        }
                                        .buttonStyle(PressableStyle(scale: 0.92))
                                    }
                                }
                            }
                            .scrollIndicators(.hidden)
                        }
                        .transition(.scale.combined(with: .opacity))
                    }
                }
                .padding(20)
                .animation(.spring(response: 0.45, dampingFraction: 0.8), value: model.pendingAnnotations)
            }
            .background(Theme.paper.ignoresSafeArea())
            .navigationTitle("보류함")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("닫기") { dismiss() } } }
        }
        .presentationDetents([.medium, .large])
        .fontDesign(.rounded)
    }
}
