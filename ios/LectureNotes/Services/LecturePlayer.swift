import AVFoundation
import Combine

/// 필기를 누르면 그 순간의 녹음을 들려준다. 기기에 녹음(m4a)이 있으면 그것을, 없으면 서버 녹음을 재생한다.
@MainActor
final class LecturePlayer: ObservableObject {
    @Published private(set) var isActive = false
    @Published private(set) var isPlaying = false
    @Published private(set) var currentMs = 0
    @Published private(set) var durationMs = 0

    private var player: AVPlayer?
    private var url: URL?
    private var timeObserver: Any?

    /// 필기는 설명이 끝날 즈음 붙으므로 조금 앞(3초)에서부터 들려준다
    func play(_ url: URL, fromMs ms: Int) {
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
        try? AVAudioSession.sharedInstance().setActive(true)
        if self.url != url || player == nil {
            stop()
            let item = AVPlayerItem(url: url)
            let player = AVPlayer(playerItem: item)
            timeObserver = player.addPeriodicTimeObserver(forInterval: CMTime(value: 1, timescale: 4), queue: .main) {
                [weak self] time in
                MainActor.assumeIsolated {
                    guard let self, let item = self.player?.currentItem else { return }
                    self.currentMs = Int(time.seconds * 1000)
                    let duration = item.duration.seconds
                    if duration.isFinite { self.durationMs = Int(duration * 1000) }
                    self.isPlaying = self.player?.timeControlStatus != .paused
                }
            }
            self.player = player
            self.url = url
        }
        let start = CMTime(seconds: max(0, Double(ms) / 1000 - 3), preferredTimescale: 600)
        player?.seek(to: start, toleranceBefore: .zero, toleranceAfter: .zero)
        player?.play()
        isActive = true
        isPlaying = true
    }

    func togglePause() {
        guard let player else { return }
        if player.timeControlStatus == .paused { player.play() } else { player.pause() }
        isPlaying = player.timeControlStatus != .paused
    }

    func seek(toFraction fraction: Double) {
        guard durationMs > 0 else { return }
        player?.seek(to: CMTime(seconds: fraction * Double(durationMs) / 1000, preferredTimescale: 600))
    }

    func stop() {
        player?.pause()
        if let timeObserver { player?.removeTimeObserver(timeObserver) }
        timeObserver = nil
        player = nil
        url = nil
        isActive = false
        isPlaying = false
        currentMs = 0
        durationMs = 0
    }
}

extension Int {
    /// 밀리초 → "1:05" / "1:02:05"
    var clockText: String {
        let s = Swift.max(0, self / 1000)
        let h = s / 3600, m = (s % 3600) / 60, sec = s % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, sec) : String(format: "%d:%02d", m, sec)
    }
}
