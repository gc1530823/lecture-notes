import PDFKit
import SwiftUI

/// 시험 예상 지도: 그 자료로 들은 모든 강의에서 교수님이 시험에 나온다고 하거나 강조한 페이지를 색으로 보여 주고,
/// 점수가 높은 페이지의 예상 문제(모범 답안·출제 이유)를 보여 준다.
struct ExamMapView: View {
    @EnvironmentObject private var store: DocumentStore
    let document: LocalDocument

    @State private var map: ExamMap?
    @State private var errorMessage: String?
    @State private var thumbnails: [Int: UIImage] = [:]
    @State private var scrollTarget: Int?

    /// initialMap이 있으면(데모 모드) 서버에 묻지 않고 그대로 보여 준다.
    init(document: LocalDocument, initialMap: ExamMap? = nil) {
        self.document = document
        _map = State(initialValue: initialMap)
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if let map {
                        content(map)
                    } else if let errorMessage {
                        ContentUnavailableView("불러오지 못했어요", systemImage: "wifi.slash", description: Text(errorMessage))
                    } else {
                        ProgressView("강의를 모아 분석하는 중…").frame(maxWidth: .infinity).padding(.top, 60)
                    }
                }
                .padding(18)
            }
            .onChange(of: scrollTarget) { _, target in
                guard let target else { return }
                withAnimation(.snappy) { proxy.scrollTo("rank-\(target)", anchor: .center) }
                scrollTarget = nil
            }
        }
        .background(Theme.paper.ignoresSafeArea())
        .navigationTitle("시험 예상 지도")
        .navigationBarTitleDisplayMode(.inline)
        .fontDesign(.rounded)
        .task {
            if map == nil { await poll() }
            await loadThumbnails()
        }
    }

    @ViewBuilder
    private func content(_ map: ExamMap) -> some View {
        if map.lectures == 0 {
            EmptyNote(message: "강의를 녹음하면 교수님이 강조한 곳을 찾아 표시해요")
        } else {
            Text("강의 \(map.lectures)회를 분석했어요. 색이 진할수록 시험에 나올 가능성이 높아요.")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)], spacing: 12) {
                ForEach(map.pages, id: \.pageNo) { page in
                    HeatCell(page: page, image: thumbnails[page.pageNo]) { scrollTarget = page.pageNo }
                }
            }

            Text("시험에 나올 곳").font(.title3.weight(.bold)).padding(.top, 6)
            let ranked = map.top.compactMap { no in map.pages.first { $0.pageNo == no } }
            if ranked.isEmpty {
                EmptyNote(message: "아직 강조하거나 시험에 나온다고 한 곳이 없어요")
            }
            ForEach(Array(ranked.enumerated()), id: \.element.pageNo) { index, page in
                RankCard(rank: index + 1, page: page,
                         questions: map.questions.first { $0.pageNo == page.pageNo }?.questions ?? [])
                    .id("rank-\(page.pageNo)")
            }
            if !ranked.isEmpty {
                predictButton(map)
            }
        }
    }

    private func predictButton(_ map: ExamMap) -> some View {
        let building = map.job.status == "building"
        let needed = map.questions.count < map.top.count || map.questions.contains { $0.stale }
        return Button {
            Task {
                do {
                    _ = try await APIClient.current().startExamQuestions(documentId: document.id)
                    await poll()
                } catch {
                    errorMessage = error.localizedDescription
                }
            }
        } label: {
            HStack(spacing: 8) {
                if building {
                    ProgressView().tint(.white)
                    Text(map.job.total > 0 ? "예상 문제 만드는 중… (\(map.job.done)/\(map.job.total)쪽)" : "예상 문제 만드는 중…")
                } else {
                    Image(systemName: "sparkles")
                    Text(needed ? "예상 문제 만들기" : "예상 문제 다시 만들기")
                }
            }
            .font(.headline)
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .frame(height: 52)
            .background(Theme.accent.gradient, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .buttonStyle(PressableStyle(scale: 0.97))
        .disabled(building)
    }

    private func poll() async {
        while !Task.isCancelled {
            do {
                let result = try await APIClient.current().examMap(documentId: document.id)
                withAnimation(.snappy) { map = result }
                errorMessage = nil
                if result.job.status != "building" { return }
            } catch {
                errorMessage = error.localizedDescription
                return
            }
            try? await Task.sleep(for: .seconds(2))
        }
    }

    private func loadThumbnails() async {
        let pdf = store.pdf(for: document)
        for index in 0..<(pdf?.pageCount ?? 0) {
            if let image = await PageRenderer.shared.image(for: pdf, pageIndex: index, width: 500) {
                thumbnails[index + 1] = image
            }
        }
    }
}

extension ExamPageScore {
    var heatColor: Color {
        switch level {
        case "high": AnnotationType.exam.inkColor
        case "medium": AnnotationType.emphasis.inkColor
        default: .clear
        }
    }

    var heatLabel: String? {
        switch level {
        case "high": "시험 유력"
        case "medium": "나올 수 있음"
        default: nil
        }
    }

    var heatSymbol: String {
        level == "high" ? "flame.fill" : "exclamationmark.triangle.fill"
    }
}

private struct HeatCell: View {
    let page: ExamPageScore
    let image: UIImage?
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            ZStack(alignment: .bottom) {
                Group {
                    if let image {
                        Image(uiImage: image).resizable().scaledToFit()
                    } else {
                        Color.white.aspectRatio(16 / 9, contentMode: .fit)
                    }
                }
                .overlay(page.heatColor.opacity(page.score * 0.38))
                HStack {
                    Text("\(page.pageNo)")
                        .font(.caption.weight(.heavy))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 2)
                        .background(.background, in: RoundedRectangle(cornerRadius: 7))
                    Spacer()
                    if let label = page.heatLabel {
                        Label(label, systemImage: page.heatSymbol)
                            .font(.caption2.weight(.heavy))
                            .foregroundStyle(.white)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(page.heatColor, in: Capsule())
                    }
                }
                .padding(6)
            }
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(page.heatColor.opacity(0.85), lineWidth: page.level == "low" ? 0 : 3)
            }
            .shadow(color: .black.opacity(0.1), radius: 6, y: 3)
        }
        .buttonStyle(PressableStyle(scale: 0.97))
    }
}

private struct RankCard: View {
    let rank: Int
    let page: ExamPageScore
    let questions: [PredictedQuestion]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Text("\(rank)")
                    .font(.headline.weight(.heavy))
                    .foregroundStyle(page.heatColor)
                    .frame(width: 34, height: 34)
                    .background(page.heatColor.opacity(0.16), in: RoundedRectangle(cornerRadius: 9))
                Text("\(page.pageNo)쪽").font(.headline)
                if let label = page.heatLabel {
                    Label(label, systemImage: page.heatSymbol).font(.subheadline.weight(.bold)).foregroundStyle(page.heatColor)
                }
            }
            FlowReasons(reasons: page.reasons)
            ForEach(Array(questions.enumerated()), id: \.offset) { index, question in
                VStack(alignment: .leading, spacing: 6) {
                    (Text("예상 \(index + 1)  ").foregroundStyle(Theme.accent) + Text(question.question))
                        .font(.subheadline.weight(.bold))
                    DisclosureGroup("모범 답안 보기") {
                        Text(question.answer)
                            .font(.subheadline)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.top, 4)
                    }
                    .font(.footnote.weight(.bold))
                    .tint(Theme.accent)
                    Label(question.reason, systemImage: "lightbulb")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(12)
                .background(Theme.accent.opacity(0.06), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
        }
        .card(padding: 14)
    }
}

/// 이유 칩을 두 개씩 줄 맞춰 보여 준다
private struct FlowReasons: View {
    let reasons: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(stride(from: 0, to: reasons.count, by: 2)), id: \.self) { start in
                HStack(spacing: 6) {
                    ForEach(reasons[start..<min(start + 2, reasons.count)], id: \.self) { reason in
                        Text(reason)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 5)
                            .background(Color.secondary.opacity(0.12), in: Capsule())
                    }
                }
            }
        }
    }
}
