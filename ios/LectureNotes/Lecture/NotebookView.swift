import SwiftUI

/// 노트 모드: 디지털 필기 노트처럼 — 색 머리띠(제목·날짜·10색), 모눈 종이, 주제마다 "1. 제목" 아래로 AI가 한 줄씩 써 내려간다.
struct NotebookView: View {
    let title: String
    let date: Date
    let pages: [Page]
    let annotations: [Annotation]
    let currentPage: Int
    let isRecording: Bool
    @Binding var selectedID: Int?
    var canPlay = false
    var beyondIDs: Set<Int> = []
    var onPlay: (Annotation) -> Void = { _ in }

    static let colors: [Color] = [
        Color(hex: 0xD9D1FF), Color(hex: 0xC7EBFF), Color(hex: 0xC2F0CC), Color(hex: 0xFFF1A8), Color(hex: 0xFFD6A8),
        Color(hex: 0xFFC9D4), Color(hex: 0xF4D8FF), Color(hex: 0xD6E7C8), Color(hex: 0xE8E2D6), Color(hex: 0xDFE3EA),
    ]
    @AppStorage("notebookColor") private var colorIndex = 0

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    header
                    VStack(alignment: .leading, spacing: 14) {
                        ForEach(pages) { page in
                            section(page).id("sec-\(page.pageNo)")
                        }
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 12)
                    .frame(maxWidth: .infinity, minHeight: 300, alignment: .topLeading)
                    .background(GridPaper())
                }
                .background(Color(hex: 0xFFFEFB))
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                .shadow(color: .black.opacity(0.10), radius: 12, y: 5)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .padding(.bottom, 120)
            }
            .onChange(of: currentPage) { _, page in
                withAnimation(.snappy) { proxy.scrollTo("sec-\(page)", anchor: .top) }
            }
            .onChange(of: annotations.count) { _, _ in
                guard let last = annotations.last(where: { $0.pageNo == currentPage }) else { return }
                withAnimation(.snappy) { proxy.scrollTo(last.id, anchor: .bottom) }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .trailing, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("title").font(.caption2).foregroundStyle(.black.opacity(0.45))
                Text(title).font(.system(.headline, design: .serif)).foregroundStyle(Color(hex: 0x2B2B3A)).lineLimit(1)
                Spacer()
                Text(date.formatted(.dateTime.year(.twoDigits).month(.twoDigits).day(.twoDigits)))
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.black.opacity(0.45))
            }
            HStack(spacing: 4) {
                ForEach(Self.colors.indices, id: \.self) { index in
                    Button { colorIndex = index } label: {
                        Circle()
                            .fill(Self.colors[index])
                            .frame(width: 13, height: 13)
                            .overlay(Circle().strokeBorder(.black.opacity(colorIndex == index ? 0.45 : 0.12),
                                                           lineWidth: colorIndex == index ? 2 : 1))
                    }
                    .accessibilityLabel("노트 색 \(index + 1)")
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Self.colors[min(colorIndex, Self.colors.count - 1)])
    }

    private func section(_ page: Page) -> some View {
        let notes = annotations.filter { $0.pageNo == page.pageNo && !$0.pending }
        let isNow = page.pageNo == currentPage
        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Text("\(page.pageNo).").foregroundStyle(Color(hex: 0x6B5FD6))
                Text(page.text?.isEmpty == false ? page.text! : (isRecording && isNow ? "주제를 듣는 중…" : "제목 없음"))
                    .foregroundStyle(page.text?.isEmpty == false ? Color(hex: 0x2B2B3A) : .secondary)
                    .background(alignment: .bottom) {
                        Self.colors[min(colorIndex, Self.colors.count - 1)].frame(height: 8).offset(y: -2)
                    }
            }
            .font(.system(.subheadline, design: .serif).weight(.semibold))
            if notes.isEmpty {
                Text(isRecording && isNow ? "교수님 설명을 듣고 있어요. 필기가 여기에 써져요." : "아직 필기가 없어요")
                    .font(.footnote)
                    .foregroundStyle(.tertiary)
                    .padding(.leading, 8)
            }
            ForEach(notes) { note in
                NoteLine(annotation: note, isSelected: selectedID == note.id, isBeyond: beyondIDs.contains(note.id),
                         canPlay: canPlay && note.id > 0) { onPlay(note) }
                    .id(note.id)
                    .onTapGesture { selectedID = selectedID == note.id ? nil : note.id }
                    .transition(.opacity.combined(with: .move(edge: .leading)))
            }
        }
    }
}

/// 노트 한 줄: 종류 표시 + "개념: 설명"의 개념은 주황, 둘째 문장부터는 → 로 들여 쓰기
private struct NoteLine: View {
    let annotation: Annotation
    let isSelected: Bool
    let isBeyond: Bool
    let canPlay: Bool
    let onPlay: () -> Void

    private var mark: String {
        switch annotation.type {
        case .explanation: "-"
        case .example: "예)"
        case .emphasis: "!"
        case .exam: "★"
        case .notice: "공지)"
        case .tip: "(+)"
        case .qa: "Q."
        }
    }

    private var color: Color {
        switch annotation.type {
        case .example: Color(hex: 0x2F7FD1)
        case .notice: Color(hex: 0xD2691E)
        case .tip, .qa: Color(hex: 0x0D85CC)
        default: Color(hex: 0x2B2B3A)
        }
    }

    private var highlight: Color? {
        switch annotation.type {
        case .exam: Color(red: 1, green: 0.59, blue: 0.69).opacity(0.55)
        case .emphasis: Color(red: 1, green: 0.89, blue: 0.43).opacity(0.7)
        default: nil
        }
    }

    var body: some View {
        let sentences = annotation.text
            .split(whereSeparator: { $0 == "\n" })
            .flatMap { $0.split(separator: ". ", omittingEmptySubsequences: true) }
            .map { String($0) }
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Text(mark)
                .foregroundStyle(annotation.type == .exam ? AnnotationType.exam.inkColor : Color(hex: 0x8A86A0))
                .frame(minWidth: 14, alignment: .leading)
            VStack(alignment: .leading, spacing: 1) {
                mainLine(sentences.first ?? annotation.text)
                    .background(alignment: .bottom) { highlight.map { $0.frame(height: 9) } }
                ForEach(Array(sentences.dropFirst().enumerated()), id: \.offset) { _, sentence in
                    Text("→ \(sentence)").foregroundStyle(Color(hex: 0x55536A)).padding(.leading, 12)
                }
                if isBeyond {
                    Text("교수님만 말함")
                        .font(.caption2.weight(.heavy))
                        .foregroundStyle(Theme.accent)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Theme.accent.opacity(0.1), in: Capsule())
                }
            }
            Spacer(minLength: 0)
            if canPlay {
                Button(action: onPlay) { Image(systemName: "play.fill").font(.caption) }
                    .foregroundStyle(Theme.accent)
                    .accessibilityLabel("이 필기 때 녹음 듣기")
            }
        }
        .font(.system(.subheadline, design: .serif))
        .padding(.leading, 8)
        .padding(.vertical, 1)
        .overlay {
            if isSelected { RoundedRectangle(cornerRadius: 4).strokeBorder(Theme.accent, lineWidth: 2).padding(-2) }
        }
        .opacity(annotation.id < 0 ? 0.5 : 1)
    }

    private func mainLine(_ text: String) -> Text {
        // "개념: 설명" 꼴이면 개념을 주황 글씨로
        if let colon = text.firstIndex(where: { $0 == ":" || $0 == "：" }), text.distance(from: text.startIndex, to: colon) <= 18 {
            let term = String(text[..<colon])
            let rest = String(text[text.index(after: colon)...]).trimmingCharacters(in: .whitespaces)
            return Text(term).foregroundColor(Color(hex: 0xE0582E)) + Text(" \(rest)").foregroundColor(color)
        }
        return Text(text).foregroundColor(color)
    }
}

/// 모눈 종이 배경
private struct GridPaper: View {
    var body: some View {
        Canvas { context, size in
            var path = Path()
            let step: CGFloat = 22
            stride(from: 0, through: size.width, by: step).forEach { x in
                path.move(to: CGPoint(x: x, y: 0)); path.addLine(to: CGPoint(x: x, y: size.height))
            }
            stride(from: 0, through: size.height, by: step).forEach { y in
                path.move(to: CGPoint(x: 0, y: y)); path.addLine(to: CGPoint(x: size.width, y: y))
            }
            context.stroke(path, with: .color(Color(hex: 0xEEF0F4)), lineWidth: 1)
        }
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }
}
