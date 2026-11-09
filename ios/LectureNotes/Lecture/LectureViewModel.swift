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
    let player = LecturePlayer()

    // 자막 모드 (청각장애 학생·시끄러운 강의실): 지금 설명하는 문단 표시, 큰 자막, 시험·공지·과제 때 강한 진동
    @Published var captionMode = UserDefaults.standard.bool(forKey: "captionMode") {
        didSet { UserDefaults.standard.set(captionMode, forKey: "captionMode") }
    }
    @Published private(set) var spokenSpot: SpokenSpot?
    @Published private(set) var captionLines: [String] = []
    @Published var importantAlert: ImportantAlert?
    /// 실시간 용어 사전: 모은 용어와, 방금 나와 화면에 잠깐 띄울 용어
    @Published private(set) var terms: [GlossaryTerm] = []
    @Published var freshTerm: GlossaryTerm?
    /// 강의가 끝난 뒤: 슬라이드에 없는 설명을 담은 필기와 그 비율
    @Published private(set) var beyond: BeyondSlides?

    private let store: DocumentStore
    private let socket = LectureSocket()
    private var followingEstimate = false
    private var demoMode = false
    private var lastManualTurn = Date.distantPast
    private static let manualPause: TimeInterval = 20
    private static let followConfidence = 0.6

    init(document: LocalDocument, store: DocumentStore, existingSession: SavedSession? = nil) {
        self.document = document
        self.pages = document.document.pages
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
        socket.onTerm = { [weak self] term in self?.receive(term) }
        socket.onPageAdded = { [weak self] page in self?.receivePageAdded(page) }
        socket.onPageTitle = { [weak self] pageNo, title in self?.receivePageTitle(pageNo, title) }
        socket.onSpoken = { [weak self] page, blockId, text in self?.receiveSpoken(page: page, blockId: blockId, text: text) }
    }

    /// 노트 모드에서는 수업 중에 쪽이 늘고 제목이 붙는다
    @Published private(set) var pages: [Page]
    var isNotebook: Bool { document.document.isNotebook }

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

    private func receive(_ term: GlossaryTerm) {
        guard !terms.contains(where: { $0.id == term.id }) else { return }
        withAnimation(.spring(response: 0.45, dampingFraction: 0.8)) {
            terms.append(term)
            freshTerm = term
        }
    }

    private func receivePageAdded(_ page: Page) {
        guard !pages.contains(where: { $0.pageNo == page.pageNo }) else { return }
        withAnimation(.snappy) {
            pages.append(page)
            if autoFollow { currentPage = page.pageNo }
        }
    }

    private func receivePageTitle(_ pageNo: Int, _ title: String) {
        guard let index = pages.firstIndex(where: { $0.pageNo == pageNo }) else { return }
        withAnimation(.snappy) { pages[index].text = title }
    }

    private func receiveSpoken(page: Int, blockId: Int?, text: String) {
        withAnimation(.snappy) {
            spokenSpot = SpokenSpot(pageNo: page, blockId: blockId)
            captionLines = Array((captionLines + [text]).suffix(3))
        }
    }

    /// 자막 모드에서 놓치면 안 되는 순간: 진동을 세게 세 번 주고 화면 위에 크게 띄운다
    private func alertImportant(symbol: String, title: String, text: String, banner: Bool = true) {
        guard captionMode else { return }
        let haptic = UINotificationFeedbackGenerator()
        for i in 0..<3 {
            DispatchQueue.main.asyncAfter(deadline: .now() + Double(i) * 0.35) { haptic.notificationOccurred(.warning) }
        }
        if banner {
            withAnimation(.spring(response: 0.45, dampingFraction: 0.75)) {
                importantAlert = ImportantAlert(symbol: symbol, title: title, text: text)
            }
        }
    }

    private func receive(_ task: LectureTask) {
        guard !tasks.contains(where: { $0.id == task.id }) else { return }
        // 과제는 위쪽 과제 배너가 이미 크게 뜨므로 진동만 더한다
        alertImportant(symbol: "list.clipboard", title: "새 과제", text: task.title, banner: false)
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
            terms = (try? await api.glossary(sessionId: session.id)) ?? []
            if isNotebook { pages = try await api.document(id: document.id).pages }
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
        await loadBeyondSlides()
        if isNotebook {
            // 마지막 주제의 제목은 연결이 끊긴 뒤에 붙으므로 잠시 뒤 다시 받아 온다
            try? await Task.sleep(for: .seconds(4))
            if let updated = try? await APIClient.current().document(id: document.id) { pages = updated.pages }
        }
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

    /// 녹음을 들을 수 있는지 (녹음 중에는 마이크와 겹치지 않게 막는다)
    var canPlayRecording: Bool { session != nil && phase == .ended && recordingURL != nil }

    private var recordingURL: URL? {
        guard let session else { return nil }
        let local = store.recordingURL(for: session)
        if FileManager.default.fileExists(atPath: local.path) { return local }
        // 기기에 녹음이 없으면(녹음 파일로 정리한 강의 등) 서버 녹음을 스트리밍한다
        return try? APIClient.current().baseURL.appending(path: "sessions/\(session.id)/audio")
    }

    func playRecording(at annotation: Annotation) {
        guard let url = recordingURL else { return }
        player.play(url, fromMs: annotation.startMs)
    }

    func loadBeyondSlides() async {
        guard let session, phase == .ended, !demoMode else { return }
        beyond = try? await APIClient.current().beyondSlides(sessionId: session.id)
    }

    func catchUp(minutes: Double) async -> CatchUp? {
        guard let session else { return nil }
        do {
            return try await APIClient.current().catchUp(sessionId: session.id, minutes: minutes)
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    /// 수업 중 질문. 답은 질문한 페이지의 관련 문단 옆에 질문 포스트잇으로 붙는다.
    func ask(_ question: String) async {
        guard let session else { return }
        let page = currentPage
        do {
            let note = try await APIClient.current().ask(sessionId: session.id, question: question, pageNo: page)
            receive(note)
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
        if annotation.type == .exam {
            alertImportant(symbol: "star.fill", title: "시험에 나온다고 했어요", text: annotation.text)
        } else if annotation.type == .notice {
            alertImportant(symbol: "megaphone.fill", title: "공지", text: annotation.text)
        }
    }

    /// 데모 모드: 노트 모드 화면 (강의자료 없는 수업)
    func applyNotebookDemo() {
        pages = DemoData.notebookPages
        applyDemo(annotations: DemoData.notebookNotes, phase: .ended, caption: nil)
        currentPage = 1
    }

    /// 데모 모드: 자막 모드 화면
    func applyCaptionDemo(lines: [String], spot: SpokenSpot, alert: ImportantAlert?) {
        captionMode = true
        captionLines = lines
        spokenSpot = spot
        importantAlert = alert
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
