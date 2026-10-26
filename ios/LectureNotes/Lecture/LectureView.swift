import PDFKit
import SwiftUI

/// 강의 화면: 위에는 강의자료 페이지(형광펜 + 깃발), 아래에는 그 페이지의 포스트잇 필기.
struct LectureView: View {
    @StateObject private var model: LectureViewModel
    @State private var selectedAnnotationID: Int?
    @State private var editing: Annotation?
    @State private var showingSummary = false
    private let demo: DemoScreen?

    init(document: LocalDocument, store: DocumentStore, session: SavedSession?, demo: DemoScreen? = nil) {
        let model = LectureViewModel(document: document, store: store, existingSession: session)
        switch demo {
        case .lecture:
            model.applyDemo(annotations: DemoData.annotations, phase: .ended, caption: nil)
        case .recording:
            model.applyDemo(annotations: Array(DemoData.annotations.prefix(3)), phase: .recording,
                            caption: "그래서 학습률은 보통 0.01이나 0.001부터 시작해서 줄여 가요")
        case .live:
            model.applyDemo(annotations: [], phase: .recording, caption: "")
        default:
            break
        }
        _model = StateObject(wrappedValue: model)
        self.demo = demo
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
            if model.phase == .ended, model.session != nil {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showingSummary = true } label: { Image(systemName: "sparkles.rectangle.stack") }
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
                SummaryView(sessionID: session.id, initialSummary: demo == nil ? nil : DemoData.summary,
                            onSelectPage: { page in
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
        .task {
            if demo == .live {
                await model.runDemoLive()
            } else if demo == nil {
                await model.loadExistingAnnotations()
            }
        }
        .sensoryFeedback(.impact(weight: .light), trigger: model.annotations.count)
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
                        selectedAnnotationID: $selectedAnnotationID
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
                onDelete: { annotation in Task { await model.delete(annotation) } }
            )
            .frame(maxHeight: .infinity)
            .safeAreaInset(edge: .bottom) {
                VStack(spacing: 10) {
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
            PageDots(count: model.pages.count, current: model.currentPage)
        }
        .padding(.horizontal, 20)
        .padding(.top, 6)
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
