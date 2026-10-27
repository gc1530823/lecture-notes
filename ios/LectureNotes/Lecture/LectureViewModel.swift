import Foundation
import PDFKit
import SwiftUI

/// 강의 화면 하나의 상태: 보는 페이지, 녹음, 실시간 필기.
@MainActor
final class LectureViewModel: ObservableObject {
    enum Phase: Equatable {
        case ready          // 아직 녹음 전
        case recording
        case finishing      // 남은 필기를 받고 요약을 요청하는 중
        case ended
    }

    let document: LocalDocument
    let pdf: PDFDocument?
    let recorder = SpeechRecorder()

    @Published var currentPage = 1 {
        didSet {
            guard currentPage != oldValue else { return }
            if followingEstimate { return }
            // 사용자가 직접 넘긴 페이지 (서버의 신호 A). 잠시 자동 넘김을 멈춘다.
            lastManualTurn = Date()
            if phase == .recording { socket.sendPageView(currentPage) }
        }
    }
    /// 교수님이 설명 중인 페이지로 화면을 자동으로 넘길지
    @Published var autoFollow = true
    /// 서버가 추정한 지금 설명 중인 페이지와 확신
    @Published private(set) var estimatedPage: Int?
    @Published private(set) var estimateConfidence: Double = 0
    /// 이번 강의에서 교수님이 낸 과제
    @Published private(set) var tasks: [LectureTask] = []
    /// 즉시 필기(임시 포스트잇). 음수 id로 진짜 필기와 구분한다.
    @Published private(set) var previews: [Annotation] = []
    private var previewIDs: [String: Int] = [:]
    private var nextPreviewID = -1
    /// 방금 들어온 과제 (화면 위 배너로 알린다)
    @Published var freshTask: LectureTask?
    @Published private(set) var annotations: [Annotation] = []
    @Published private(set) var phase: Phase = .ready
    @Published private(set) var session: SavedSession? = nil
    @Published var errorMessage: String? = nil
    /// 방금 들어온 필기. 목록에서 잠깐 강조하고 그 위치로 스크롤한다.
    @Published private(set) var latestAnnotationID: Int? = nil

    private let store: DocumentStore
    private let socket = LectureSocket()
    private var followingEstimate = false
    private var demoMode = false
    private var lastManualTurn = Date.distantPast
    private static let manualPause: TimeInterval = 20
    private static let followConfidence = 0.6

    init(document: LocalDocument, store: DocumentStore, existingSession: SavedSession? = nil) {
        self.document = document
        self.store = store
        self.pdf = store.pdf(for: document)
        self.session = existingSession
        self.phase = existingSession == nil ? .ready : .ended

        recorder.contextualStrings = document.document.keywords
        recorder.onSegment = { [weak self] text, start, end in
            self?.socket.sendTranscript(text: text, startMs: start, endMs: end)
        }
        recorder.onError = { [weak self] message in self?.errorMessage = message }
        socket.onAnnotation = { [weak self] annotation in self?.receive(annotation) }
        socket.onError = { [weak self] message in self?.errorMessage = message }
        socket.onPageEstimate = { [weak self] page, confidence in self?.receiveEstimate(page: page, confidence: confidence) }
        socket.onTask = { [weak self] task in self?.receive(task) }
        socket.onPreview = { [weak self] preview in self?.receive(preview) }
        socket.onPreviewsResolved = { [weak self] ids in self?.resolvePreviews(ids) }
    }

    var pages: [Page] { document.document.pages }

    func annotations(onPage pageNo: Int) -> [Annotation] {
        (annotations + previews).filter { $0.pageNo == pageNo && !$0.pending }
    }

    private func receive(_ preview: AnnotationPreview) {
        let id = nextPreviewID
        nextPreviewID -= 1
        previewIDs[preview.id] = id
        let note = Annotation(id: id, sessionId: session?.id ?? "", pageNo: preview.pageNo, blockId: preview.blockId,
                              type: preview.type, text: preview.text, startMs: preview.startMs, editedByUser: false)
        withAnimation(.spring(response: 0.45, dampingFraction: 0.7)) { previews.append(note) }
        latestAnnotationID = id
    }

    private func resolvePreviews(_ keys: [String]) {
        let ids = Set(keys.compactMap { previewIDs.removeValue(forKey: $0) })
        withAnimation(.easeInOut(duration: 0.3)) { previews.removeAll { ids.contains($0.id) } }
    }

    /// 어느 페이지인지 확실하지 않아 보류함에 있는 필기
    var pendingAnnotations: [Annotation] { annotations.filter(\.pending) }

    /// 보류함의 필기를 고른 페이지에 붙이고, 그 페이지로 넘어간다
    func place(_ annotation: Annotation, onPage pageNo: Int) async {
        do {
            let placed: Annotation
            if demoMode {
                placed = Annotation(id: annotation.id, sessionId: annotation.sessionId, pageNo: pageNo, blockId: nil,
                                    type: annotation.type, text: annotation.text, startMs: annotation.startMs,
                                    editedByUser: annotation.editedByUser)
            } else {
                placed = try await APIClient.current().placeAnnotation(id: annotation.id, pageNo: pageNo)
            }
            withAnimation(.spring(response: 0.5, dampingFraction: 0.7)) {
                annotations.removeAll { $0.id == placed.id }
                annotations.append(placed)
                currentPage = pageNo
            }
            latestAnnotationID = placed.id
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    var isDemo: Bool { demoMode }

    func setDone(_ task: LectureTask, _ done: Bool) async {
        do {
            var updated = task
            updated.done = done
            if !demoMode { updated = try await APIClient.current().setTaskDone(id: task.id, done: done) }
            replace(updated)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// AI와 바로 하기: 강의 내용을 근거로 초안을 만든다
    func draft(_ task: LectureTask) async -> LectureTask? {
        do {
            var updated = task
            if demoMode {
                try? await Task.sleep(for: .seconds(1.5))
                updated.draft = DemoData.draft
            } else {
                updated = try await APIClient.current().draftTask(id: task.id)
            }
            replace(updated)
            return updated
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    private func replace(_ task: LectureTask) {
        if let index = tasks.firstIndex(where: { $0.id == task.id }) { tasks[index] = task }
    }

    private func receive(_ task: LectureTask) {
        guard !tasks.contains(where: { $0.id == task.id }) else { return }
        withAnimation(.spring(response: 0.5, dampingFraction: 0.75)) {
            tasks.append(task)
            freshTask = task
        }
    }

    private func receiveEstimate(page: Int, confidence: Double) {
        estimatedPage = page
        estimateConfidence = confidence
        follow(to: page, confidence: confidence)
    }

    private func follow(to page: Int, confidence: Double) {
        guard autoFollow, phase == .recording, page != currentPage, page >= 1, page <= pages.count,
              confidence >= Self.followConfidence,
              Date().timeIntervalSince(lastManualTurn) >= Self.manualPause else { return }
        followingEstimate = true
        withAnimation(.spring(response: 0.5, dampingFraction: 0.85)) { currentPage = page }
        followingEstimate = false
    }

    func loadExistingAnnotations() async {
        guard let session, phase == .ended else { return }
        do {
            let api = try APIClient.current()
            annotations = try await api.annotations(sessionId: session.id)
            tasks = try await api.tasks(sessionId: session.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func startLecture() async {
        guard phase == .ready else { return }
        guard await SpeechRecorder.requestPermissions() else {
            errorMessage = "설정 앱에서 마이크와 음성 인식 권한을 켜 주세요."
            return
        }
        do {
            let api = try APIClient.current()
            let remote = try await api.createSession(documentId: document.id)
            let saved = store.newSession(id: remote.id, for: document.id)
            session = saved

            socket.connect(to: api.streamURL(sessionId: remote.id))
            socket.sendPageView(currentPage, initial: true)
            try recorder.start(recordingURL: store.recordingURL(for: saved))
            phase = .recording
        } catch {
            socket.disconnect()
            errorMessage = error.localizedDescription
        }
    }

    func stopLecture() async {
        guard phase == .recording, let session else { return }
        phase = .finishing
        recorder.stop()
        // 마지막 받아쓰기가 넘어가고 필기가 돌아올 시간을 준다
        try? await Task.sleep(for: .seconds(4))
        socket.sendFlush()
        try? await Task.sleep(for: .seconds(4))
        socket.disconnect()
        do {
            _ = try await APIClient.current().endSession(id: session.id)
        } catch {
            errorMessage = error.localizedDescription
        }
        phase = .ended
    }

    func leave() {
        if phase == .recording { recorder.stop() }
        socket.disconnect()
    }

    func update(_ annotation: Annotation, text: String) async {
        do {
            var updated = annotation
            if demoMode {
                updated.text = text
                updated.editedByUser = true
            } else {
                updated = try await APIClient.current().updateAnnotation(id: annotation.id, text: text)
            }
            if let index = annotations.firstIndex(where: { $0.id == updated.id }) {
                annotations[index] = updated
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func delete(_ annotation: Annotation) async {
        do {
            if !demoMode { try await APIClient.current().deleteAnnotation(id: annotation.id) }
            withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) {
                annotations.removeAll { $0.id == annotation.id }
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// 데모 모드: 서버 없이 필기와 화면 상태를 채운다.
    func applyDemo(annotations: [Annotation], phase: Phase, caption: String?, tasks: [LectureTask] = []) {
        demoMode = true
        self.annotations = annotations
        self.tasks = tasks
        self.phase = phase
        if let caption { recorder.showDemoCaption(caption, elapsed: 754) }
    }

    private func receive(_ annotation: Annotation) {
        guard !annotations.contains(where: { $0.id == annotation.id }) else { return }
        withAnimation(.spring(response: 0.55, dampingFraction: 0.62)) {
            annotations.append(annotation)
        }
        latestAnnotationID = annotation.id
    }

    /// 데모 모드: 교수님 말이 자막으로 나오고, 필기가 하나씩 붙는 장면을 재생한다.
    func runDemoLive() async {
        phase = .recording
        var elapsed: TimeInterval = 312
        let script = Array(zip(DemoData.liveCaptions, DemoData.liveAnnotations))
        for (index, (caption, annotation)) in script.enumerated() {
            var shown = ""
            for word in caption.split(separator: " ") {
                shown += (shown.isEmpty ? "" : " ") + word
                elapsed += 0.35
                recorder.showDemoCaption(shown, elapsed: elapsed, level: .random(in: 0.35...0.95))
                try? await Task.sleep(for: .milliseconds(220))
            }
            // 즉시 필기가 먼저 뜨고, 잠시 뒤 AI 필기로 바뀐다
            if annotation.pageNo == currentPage {
                receive(AnnotationPreview(id: "demo\(index)", pageNo: annotation.pageNo, blockId: annotation.blockId,
                                          type: annotation.type == .tip ? .explanation : annotation.type,
                                          text: String(caption.prefix(60)), startMs: annotation.startMs))
                try? await Task.sleep(for: .milliseconds(1400))
                resolvePreviews(["demo\(index)"])
            }
            try? await Task.sleep(for: .milliseconds(300))
            // 교수님이 다음 장으로 넘어간 장면: 서버 추정이 바뀌면 화면이 따라간다
            if annotation.pageNo != currentPage {
                receiveEstimate(page: annotation.pageNo, confidence: 0.86)
                try? await Task.sleep(for: .milliseconds(700))
            }
            receive(annotation)
            try? await Task.sleep(for: .milliseconds(index == script.count - 1 ? 0 : 900))
            // 시험 이야기 뒤에 교수님이 수업 중 과제를 낸다
            if index == 2 {
                recorder.showDemoCaption(DemoData.taskCaption, elapsed: elapsed + 3, level: 0.7)
                try? await Task.sleep(for: .milliseconds(1200))
                receive(DemoData.tasks[0])
                try? await Task.sleep(for: .milliseconds(2500))
            }
        }
    }
}
