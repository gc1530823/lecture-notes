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
            guard currentPage != oldValue, phase == .recording else { return }
            socket.sendPageView(currentPage)
        }
    }
    @Published private(set) var annotations: [Annotation] = []
    @Published private(set) var phase: Phase = .ready
    @Published private(set) var session: SavedSession? = nil
    @Published var errorMessage: String? = nil
    /// 방금 들어온 필기. 목록에서 잠깐 강조하고 그 위치로 스크롤한다.
    @Published private(set) var latestAnnotationID: Int? = nil

    private let store: DocumentStore
    private let socket = LectureSocket()

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
    }

    var pages: [Page] { document.document.pages }

    func annotations(onPage pageNo: Int) -> [Annotation] {
        annotations.filter { $0.pageNo == pageNo }
    }

    func loadExistingAnnotations() async {
        guard let session, phase == .ended else { return }
        do {
            annotations = try await APIClient.current().annotations(sessionId: session.id)
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
            socket.sendPageView(currentPage)
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
            let updated = try await APIClient.current().updateAnnotation(id: annotation.id, text: text)
            if let index = annotations.firstIndex(where: { $0.id == updated.id }) {
                annotations[index] = updated
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func delete(_ annotation: Annotation) async {
        do {
            try await APIClient.current().deleteAnnotation(id: annotation.id)
            annotations.removeAll { $0.id == annotation.id }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// 데모 모드: 서버 없이 필기와 화면 상태를 채운다.
    func applyDemo(annotations: [Annotation], phase: Phase, caption: String?) {
        self.annotations = annotations
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
        for (caption, annotation) in zip(DemoData.liveCaptions, DemoData.annotations.prefix(4)) {
            var shown = ""
            for word in caption.split(separator: " ") {
                shown += (shown.isEmpty ? "" : " ") + word
                elapsed += 0.35
                recorder.showDemoCaption(shown, elapsed: elapsed, level: .random(in: 0.35...0.95))
                try? await Task.sleep(for: .milliseconds(220))
            }
            try? await Task.sleep(for: .milliseconds(500))
            receive(annotation)
            try? await Task.sleep(for: .milliseconds(900))
        }
    }
}
