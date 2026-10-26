import Foundation

/// 강의 중 서버와 주고받는 WebSocket.
/// 보내기: page_view(보는 페이지), transcript_final(확정된 받아쓰기), flush(남은 받아쓰기 처리)
/// 받기: annotation_added(새 필기), error
@MainActor
final class LectureSocket {
    var onAnnotation: ((Annotation) -> Void)?
    var onError: ((String) -> Void)?
    /// 서버가 추정한 "지금 설명 중인 페이지"와 확신 (0~1)
    var onPageEstimate: ((Int, Double) -> Void)?
    /// 교수님이 낸 과제를 서버가 뽑아냈다
    var onTask: ((LectureTask) -> Void)?

    private var url: URL?
    private var task: URLSessionWebSocketTask?
    private var outbox: [String] = []
    private var lastPageView: String?
    private var closedByUser = false
    private var reconnectDelay: Duration = .seconds(1)

    func connect(to url: URL) {
        self.url = url
        closedByUser = false
        open()
    }

    func disconnect() {
        closedByUser = true
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
    }

    /// initial = 강의를 시작할 때 펴 둔 페이지 (직접 넘긴 것이 아님)
    func sendPageView(_ pageNo: Int, initial: Bool = false) {
        send(encode(["type": "page_view", "page": pageNo, "initial": initial]))
        lastPageView = encode(["type": "page_view", "page": pageNo, "initial": true])
    }

    func sendTranscript(text: String, startMs: Int, endMs: Int) {
        send(encode(["type": "transcript_final", "text": text, "start_ms": startMs, "end_ms": endMs]))
    }

    func sendFlush() {
        send(encode(["type": "flush"]))
    }

    private func open() {
        guard let url else { return }
        let task = URLSession.shared.webSocketTask(with: url)
        self.task = task
        task.resume()
        // 서버는 연결마다 상태를 새로 만들므로, 다시 연결하면 보던 페이지부터 알려 준다
        let pending = (lastPageView.map { [$0] } ?? []) + outbox
        outbox.removeAll()
        pending.forEach(send)
        receive(on: task)
    }

    private func send(_ message: String) {
        guard let task else {
            outbox.append(message)
            return
        }
        task.send(.string(message)) { [weak self] error in
            guard error != nil else { return }
            Task { @MainActor in self?.outbox.append(message) }
        }
    }

    private func receive(on task: URLSessionWebSocketTask) {
        task.receive { [weak self] result in
            Task { @MainActor in
                guard let self, self.task === task else { return }
                switch result {
                case let .success(.string(text)):
                    self.reconnectDelay = .seconds(1)
                    self.handle(text)
                    self.receive(on: task)
                case .success:
                    self.receive(on: task)
                case .failure:
                    self.scheduleReconnect()
                }
            }
        }
    }

    private func scheduleReconnect() {
        task = nil
        guard !closedByUser else { return }
        let delay = reconnectDelay
        reconnectDelay = min(reconnectDelay * 2, .seconds(30))
        Task { @MainActor in
            try? await Task.sleep(for: delay)
            if !self.closedByUser, self.task == nil { self.open() }
        }
    }

    private func handle(_ text: String) {
        guard let data = text.data(using: .utf8),
              let event = try? APIClient.decoder.decode(ServerEvent.self, from: data) else { return }
        switch event.type {
        case "annotation_added":
            if let annotation = event.annotation { onAnnotation?(annotation) }
        case "task_added":
            if let task = event.task { onTask?(task) }
        case "page_estimate":
            if let page = event.page, let confidence = event.confidence { onPageEstimate?(page, confidence) }
        case "error":
            onError?(event.message ?? "알 수 없는 오류")
        default:
            break
        }
    }

    private func encode(_ object: [String: Any]) -> String {
        let data = (try? JSONSerialization.data(withJSONObject: object)) ?? Data()
        return String(decoding: data, as: UTF8.self)
    }
}

private struct ServerEvent: Decodable {
    let type: String
    let annotation: Annotation?
    let message: String?
    let page: Int?
    let confidence: Double?
    let task: LectureTask?
}
