import AVFoundation
import Speech

/// 녹음 + 실시간 한국어 받아쓰기.
/// - 원본 녹음은 m4a 파일로 기기에 저장한다 (네트워크가 끊겨도 녹음은 남는다).
/// - 받아쓰기는 iOS 음성 인식(기기 내 인식이 되면 기기에서)으로 하고,
///   말이 잠깐 끊기거나 45초가 지나면 문장 단위(segment)로 끊어서 onSegment로 넘긴다.
@MainActor
final class SpeechRecorder: ObservableObject {
    @Published private(set) var isRecording = false
    @Published private(set) var partialText = ""
    @Published private(set) var elapsed: TimeInterval = 0

    /// 확정된 받아쓰기 (text, startMs, endMs). 시각은 녹음 시작 기준이다.
    var onSegment: ((String, Int, Int) -> Void)?
    var onError: ((String) -> Void)?
    /// 강의자료에서 뽑은 전문용어. 인식 정확도를 높이는 힌트로 쓴다.
    var contextualStrings: [String] = []

    private static let silenceToFinish: TimeInterval = 1.2
    private static let maxSegmentMs = 45_000

    private let engine = AVAudioEngine()
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "ko-KR"))
    private let feeder = RequestFeeder()
    private var audioFile: AVAudioFile?
    private var startDate: Date?
    private var timer: Timer?

    private var current: Segment?
    private var nextSegmentID = 0
    private var interruptionObserver: NSObjectProtocol?

    private final class Segment {
        let id: Int
        let startMs: Int
        let request: SFSpeechAudioBufferRecognitionRequest
        var task: SFSpeechRecognitionTask?
        var text = ""
        var lastChange = Date()
        var endMs: Int?
        var delivered = false

        init(id: Int, startMs: Int, request: SFSpeechAudioBufferRecognitionRequest) {
            self.id = id
            self.startMs = startMs
            self.request = request
        }
    }

    /// 데모 모드: 녹음 중인 화면을 보여 주기 위해 자막과 시간만 채운다.
    func showDemoCaption(_ text: String, elapsed: TimeInterval) {
        partialText = text
        self.elapsed = elapsed
        isRecording = true
    }

    static func requestPermissions() async -> Bool {
        let speech = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0 == .authorized) }
        }
        let microphone = await AVAudioApplication.requestRecordPermission()
        return speech && microphone
    }

    func start(recordingURL: URL) throws {
        guard !isRecording else { return }
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement)
        try session.setActive(true)

        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        let fileSettings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: format.sampleRate,
            AVNumberOfChannelsKey: format.channelCount,
            AVEncoderBitRateKey: 64_000,
        ]
        let file = try AVAudioFile(forWriting: recordingURL, settings: fileSettings,
                                   commonFormat: format.commonFormat, interleaved: format.isInterleaved)
        audioFile = file

        let feeder = feeder
        input.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, _ in
            feeder.append(buffer)
            try? file.write(from: buffer)
        }
        engine.prepare()
        try engine.start()

        startDate = Date()
        elapsed = 0
        isRecording = true
        startSegment()

        timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
        interruptionObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification, object: session, queue: .main
        ) { [weak self] notification in
            let raw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            guard raw.flatMap(AVAudioSession.InterruptionType.init(rawValue:)) == .ended else { return }
            Task { @MainActor in self?.resumeAfterInterruption() }
        }
    }

    func stop() {
        guard isRecording else { return }
        isRecording = false
        timer?.invalidate()
        timer = nil
        finishCurrentSegment(startNext: false)
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        audioFile = nil
        if let interruptionObserver { NotificationCenter.default.removeObserver(interruptionObserver) }
        interruptionObserver = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private var nowMs: Int {
        guard let startDate else { return 0 }
        return Int(Date().timeIntervalSince(startDate) * 1000)
    }

    private func tick() {
        guard isRecording else { return }
        elapsed = Double(nowMs) / 1000
        guard let current, !current.text.isEmpty else { return }
        let silent = Date().timeIntervalSince(current.lastChange) >= Self.silenceToFinish
        if silent || nowMs - current.startMs >= Self.maxSegmentMs {
            finishCurrentSegment(startNext: true)
        }
    }

    // 받아쓰기 구간

    private func startSegment() {
        guard let recognizer, recognizer.isAvailable else {
            onError?("지금은 음성 인식을 사용할 수 없습니다. 녹음은 계속됩니다.")
            return
        }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.addsPunctuation = true
        request.taskHint = .dictation
        request.contextualStrings = Array(contextualStrings.prefix(100))
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }

        nextSegmentID += 1
        let segment = Segment(id: nextSegmentID, startMs: nowMs, request: request)
        current = segment
        partialText = ""
        feeder.set(request)

        segment.task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            let text = result?.bestTranscription.formattedString
            let isFinal = result?.isFinal ?? false
            Task { @MainActor in
                self?.handle(segment: segment, text: text, isFinal: isFinal, failed: error != nil)
            }
        }
    }

    private func handle(segment: Segment, text: String?, isFinal: Bool, failed: Bool) {
        if let text, text != segment.text {
            segment.text = text
            segment.lastChange = Date()
            if segment === current { partialText = text }
        }
        guard isFinal || failed else { return }

        deliver(segment)
        // 현재 구간이 인식기 쪽에서 끝났으면 (예: 오래 말이 없음) 잠시 뒤 새 구간을 시작한다
        if segment === current {
            current = nil
            feeder.set(nil)
            Task { @MainActor in
                try? await Task.sleep(for: .milliseconds(500))
                if self.isRecording, self.current == nil { self.startSegment() }
            }
        }
    }

    private func finishCurrentSegment(startNext: Bool) {
        guard let segment = current else {
            if startNext { startSegment() }
            return
        }
        segment.endMs = nowMs
        current = nil
        feeder.set(nil)
        segment.request.endAudio()
        // 최종 결과는 handle()로 조금 뒤에 온다. 오지 않을 때를 대비해 3초 뒤에 지금까지의 글자를 보낸다.
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(3))
            self.deliver(segment)
            segment.task?.cancel()
        }
        if startNext { startSegment() }
    }

    private func deliver(_ segment: Segment) {
        guard !segment.delivered else { return }
        segment.delivered = true
        let text = segment.text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        onSegment?(text, segment.startMs, segment.endMs ?? nowMs)
    }

    // 전화 등으로 오디오가 끊겼다가 돌아오면 녹음을 다시 이어간다

    private func resumeAfterInterruption() {
        guard isRecording, !engine.isRunning else { return }
        try? AVAudioSession.sharedInstance().setActive(true)
        try? engine.start()
        finishCurrentSegment(startNext: true)
    }
}

/// 오디오 스레드에서 현재 인식 요청에 버퍼를 넣기 위한 잠금 래퍼
private final class RequestFeeder: @unchecked Sendable {
    private let lock = NSLock()
    private var request: SFSpeechAudioBufferRecognitionRequest?

    func set(_ request: SFSpeechAudioBufferRecognitionRequest?) {
        lock.lock()
        self.request = request
        lock.unlock()
    }

    func append(_ buffer: AVAudioPCMBuffer) {
        lock.lock()
        let request = request
        lock.unlock()
        request?.append(buffer)
    }
}
