import SwiftUI

/// 강의가 끝난 뒤의 요약과 퀴즈. 서버가 만드는 동안은 몇 초마다 다시 확인한다.
struct SummaryView: View {
    let sessionID: String
    let onSelectPage: (Int) -> Void

    @State private var status = "processing"
    @State private var summary: LectureSummary?
    @State private var errorMessage: String?
    /// 문항 번호 → 고른 보기
    @State private var answers: [Int: Int] = [:]

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
                    GeneratingView()
                }
            }
            .background(Theme.paper.ignoresSafeArea())
            .navigationTitle("요약·퀴즈")
            .navigationBarTitleDisplayMode(.inline)
            .animation(.easeInOut(duration: 0.3), value: summary)
        }
        .tint(Theme.accent)
        .fontDesign(.rounded)
        .task { if summary == nil { await poll() } }
    }

    private func content(_ summary: LectureSummary) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                VStack(alignment: .leading, spacing: 10) {
                    Label("한눈에 보는 강의", systemImage: "sparkles")
                        .font(.caption.weight(.heavy))
                        .foregroundStyle(.white.opacity(0.85))
                    Text(summary.overview)
                        .font(.body.weight(.medium))
                        .foregroundStyle(.white)
                        .lineSpacing(3)
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    LinearGradient(colors: [Theme.accent, Theme.accent.opacity(0.75)],
                                   startPoint: .topLeading, endPoint: .bottomTrailing),
                    in: RoundedRectangle(cornerRadius: 20, style: .continuous)
                )
                .shadow(color: Theme.accent.opacity(0.3), radius: 14, y: 6)

                section("페이지별 요약")
                ForEach(summary.pages, id: \.pageNo) { page in
                    Button { onSelectPage(page.pageNo) } label: {
                        HStack(alignment: .top, spacing: 12) {
                            Text("\(page.pageNo)")
                                .font(.subheadline.weight(.heavy))
                                .foregroundStyle(Theme.accent)
                                .frame(width: 32, height: 32)
                                .background(Theme.accent.opacity(0.12), in: RoundedRectangle(cornerRadius: 9))
                            Text(page.summary)
                                .font(.subheadline)
                                .foregroundStyle(Color.primary)
                                .multilineTextAlignment(.leading)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Image(systemName: "arrow.up.forward")
                                .font(.caption.weight(.bold))
                                .foregroundStyle(.tertiary)
                        }
                        .card(padding: 14)
                    }
                    .buttonStyle(PressableStyle(scale: 0.98))
                }

                HStack {
                    section("복습 퀴즈")
                    Spacer()
                    ScoreBadge(correct: correctCount(summary), answered: answers.count, total: summary.quiz.count)
                }
                ForEach(Array(summary.quiz.enumerated()), id: \.offset) { index, item in
                    QuizCard(number: index + 1, item: item, picked: answers[index], onPick: { choice in
                        withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) { answers[index] = choice }
                    }, onSelectPage: onSelectPage)
                }
            }
            .padding(18)
        }
    }

    private func section(_ title: String) -> some View {
        Text(title).font(.title3.weight(.bold)).padding(.top, 4)
    }

    private func correctCount(_ summary: LectureSummary) -> Int {
        answers.filter { summary.quiz.indices.contains($0.key) && summary.quiz[$0.key].answerIndex == $0.value }.count
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

private struct ScoreBadge: View {
    let correct: Int
    let answered: Int
    let total: Int

    var body: some View {
        let active = answered > 0
        HStack(spacing: 6) {
            Image(systemName: answered == total && correct == total ? "crown.fill" : "checkmark.seal.fill")
                .symbolEffect(.bounce, value: correct)
            Text("\(correct) / \(total)")
                .contentTransition(.numericText())
        }
        .font(.subheadline.weight(.heavy))
        .foregroundStyle(active ? Color.green : Color.secondary)
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(Color.green.opacity(active ? 0.14 : 0.06), in: Capsule())
        .animation(.snappy, value: correct)
    }
}

private struct QuizCard: View {
    let number: Int
    let item: QuizItem
    let picked: Int?
    let onPick: (Int) -> Void
    let onSelectPage: (Int) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("Q\(number)")
                    .font(.subheadline.weight(.heavy))
                    .foregroundStyle(Theme.accent)
                Text(item.question)
                    .font(.subheadline.weight(.bold))
            }
            ForEach(Array(item.choices.enumerated()), id: \.offset) { index, choice in
                let tint = tint(for: index)
                Button { onPick(index) } label: {
                    HStack(spacing: 10) {
                        Image(systemName: symbol(for: index))
                            .font(.body.weight(.semibold))
                            .foregroundStyle(tint ?? Color.secondary)
                            .contentTransition(.symbolEffect(.replace))
                        Text(choice)
                            .font(.subheadline)
                            .foregroundStyle(Color.primary)
                            .multilineTextAlignment(.leading)
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 11)
                    .background((tint ?? Color.secondary).opacity(tint == nil ? 0.06 : 0.14),
                                in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .overlay {
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .strokeBorder((tint ?? Color.clear).opacity(0.6), lineWidth: 1.5)
                    }
                }
                .buttonStyle(PressableStyle(scale: 0.98))
                .disabled(picked != nil)
                .modifier(Shake(amount: picked == index && index != item.answerIndex ? 1 : 0))
            }
            if let picked {
                VStack(alignment: .leading, spacing: 6) {
                    Text(picked == item.answerIndex ? "정답이에요!" : "아쉬워요, 정답은 \(item.answerIndex + 1)번")
                        .font(.footnote.weight(.heavy))
                        .foregroundStyle(picked == item.answerIndex ? Color.green : Color.red)
                    Text(item.explanation)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    Button { onSelectPage(item.pageNo) } label: {
                        Label("\(item.pageNo)쪽 다시 보기", systemImage: "arrow.uturn.backward")
                            .font(.footnote.weight(.bold))
                    }
                    .padding(.top, 2)
                }
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .card()
        .sensoryFeedback(trigger: picked) { _, new in
            guard let new else { return nil }
            return new == item.answerIndex ? .success : .error
        }
    }

    private func symbol(for index: Int) -> String {
        guard let picked else { return "circle" }
        if index == item.answerIndex { return "checkmark.circle.fill" }
        return index == picked ? "xmark.circle.fill" : "circle"
    }

    private func tint(for index: Int) -> Color? {
        guard let picked else { return nil }
        if index == item.answerIndex { return .green }
        return index == picked ? .red : nil
    }
}

/// 오답을 고르면 좌우로 흔든다 (amount가 0 → 1로 바뀌는 동안 세 번 흔들림)
private struct Shake: ViewModifier, Animatable {
    var amount: CGFloat
    var animatableData: CGFloat {
        get { amount }
        set { amount = newValue }
    }

    func body(content: Content) -> some View {
        content.offset(x: sin(amount * .pi * 6) * 6)
    }
}

/// 요약을 만드는 동안 포스트잇이 통통 튀는 애니메이션
private struct GeneratingView: View {
    var body: some View {
        VStack(spacing: 20) {
            HStack(spacing: -18) {
                ForEach(Array(AnnotationType.allCases.prefix(3).enumerated()), id: \.offset) { index, type in
                    FoldedPaper(fold: 10)
                        .fill(type.noteColor)
                        .frame(width: 54, height: 54)
                        .shadow(color: .black.opacity(0.12), radius: 3, y: 2)
                        .phaseAnimator([false, true]) { note, up in
                            note.offset(y: up ? -10 : 0).rotationEffect(.degrees(up ? Double(index - 1) * 8 : 0))
                        } animation: { _ in .spring(response: 0.5, dampingFraction: 0.6).delay(Double(index) * 0.15) }
                }
            }
            Text("필기를 모아 요약과 퀴즈를 만드는 중…")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
