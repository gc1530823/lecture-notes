import SwiftUI

/// 강의가 끝난 뒤의 요약과 퀴즈. 서버가 만드는 동안은 몇 초마다 다시 확인한다.
struct SummaryView: View {
    let sessionID: String
    let onSelectPage: (Int) -> Void

    @State private var status = "processing"
    @State private var summary: LectureSummary?
    @State private var errorMessage: String?

    /// initialSummary가 있으면(데모 모드) 서버에 묻지 않고 그대로 보여 준다.
    init(sessionID: String, initialSummary: LectureSummary? = nil, onSelectPage: @escaping (Int) -> Void) {
        self.sessionID = sessionID
        self.onSelectPage = onSelectPage
        _summary = State(initialValue: initialSummary)
    }

    var body: some View {
        NavigationStack {
            Group {
                if let summary {
                    content(summary)
                } else if status == "failed" {
                    ContentUnavailableView("요약을 만들지 못했어요", systemImage: "exclamationmark.triangle",
                                           description: Text("서버 로그를 확인해 주세요."))
                } else if let errorMessage {
                    ContentUnavailableView("서버에 연결할 수 없어요", systemImage: "wifi.slash",
                                           description: Text(errorMessage))
                } else {
                    ProgressView("요약과 퀴즈를 만드는 중…")
                }
            }
            .navigationTitle("요약·퀴즈")
            .navigationBarTitleDisplayMode(.inline)
        }
        .task { if summary == nil { await poll() } }
    }

    private func content(_ summary: LectureSummary) -> some View {
        List {
            Section("강의 요약") {
                Text(summary.overview)
            }
            Section("페이지별 요약") {
                ForEach(summary.pages, id: \.pageNo) { page in
                    Button { onSelectPage(page.pageNo) } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("\(page.pageNo)쪽").font(.caption.bold()).foregroundStyle(.tint)
                                Text(page.summary).foregroundStyle(Color.primary)
                            }
                            Spacer(minLength: 8)
                            Image(systemName: "chevron.right").font(.footnote).foregroundStyle(.tertiary)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
            Section("복습 퀴즈 \(summary.quiz.count)문항") {
                ForEach(Array(summary.quiz.enumerated()), id: \.offset) { index, item in
                    QuizCard(number: index + 1, item: item, onSelectPage: onSelectPage)
                }
            }
        }
    }

    private func poll() async {
        while !Task.isCancelled {
            do {
                let response = try await APIClient.current().summary(sessionId: sessionID)
                status = response.status
                summary = response.summary
                errorMessage = nil
                if summary != nil || status == "failed" || status == "recording" { return }
            } catch {
                errorMessage = error.localizedDescription
            }
            try? await Task.sleep(for: .seconds(3))
        }
    }
}

private struct QuizCard: View {
    let number: Int
    let item: QuizItem
    let onSelectPage: (Int) -> Void
    @State private var picked: Int?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Q\(number). \(item.question)").font(.subheadline.weight(.semibold))
            ForEach(Array(item.choices.enumerated()), id: \.offset) { index, choice in
                Button { picked = index } label: {
                    HStack {
                        Image(systemName: symbol(for: index))
                            .foregroundStyle(color(for: index))
                        Text(choice).foregroundStyle(.primary)
                        Spacer(minLength: 0)
                    }
                }
                .buttonStyle(.plain)
                .disabled(picked != nil)
            }
            if let picked {
                Text(picked == item.answerIndex ? "정답이에요!" : "오답이에요.")
                    .font(.footnote.bold())
                    .foregroundStyle(picked == item.answerIndex ? .green : .red)
                Text(item.explanation).font(.footnote).foregroundStyle(.secondary)
                Button("\(item.pageNo)쪽 다시 보기") { onSelectPage(item.pageNo) }
                    .font(.footnote)
            }
        }
        .padding(.vertical, 6)
    }

    private func symbol(for index: Int) -> String {
        guard let picked else { return "circle" }
        if index == item.answerIndex { return "checkmark.circle.fill" }
        return index == picked ? "xmark.circle.fill" : "circle"
    }

    private func color(for index: Int) -> Color {
        guard let picked else { return .secondary }
        if index == item.answerIndex { return .green }
        return index == picked ? .red : .secondary
    }
}
