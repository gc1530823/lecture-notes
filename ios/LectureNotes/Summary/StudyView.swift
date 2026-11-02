import SwiftUI

/// 공부하기: 요약·퀴즈 · 플래시카드 · 마인드맵 · 개념 메모 · 암기 · AI 튜터
struct StudyView: View {
    let sessionID: String
    var initialSummary: LectureSummary? = nil
    let onSelectPage: (Int) -> Void

    enum Tab: String, CaseIterable, Identifiable {
        case summary, flashcards, mindmap, concepts, cloze, tutor
        var id: String { rawValue }

        var label: String {
            switch self {
            case .summary: "요약·퀴즈"
            case .flashcards: "플래시카드"
            case .mindmap: "마인드맵"
            case .concepts: "개념 메모"
            case .cloze: "암기"
            case .tutor: "AI 튜터"
            }
        }

        var symbol: String {
            switch self {
            case .summary: "sparkles"
            case .flashcards: "rectangle.on.rectangle.angled"
            case .mindmap: "point.3.connected.trianglepath.dotted"
            case .concepts: "book"
            case .cloze: "brain.head.profile"
            case .tutor: "bubble.left.and.bubble.right"
            }
        }
    }

    @State private var tab: Tab = .summary

    var body: some View {
        VStack(spacing: 0) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(Tab.allCases) { item in
                        Button { withAnimation(.snappy) { tab = item } } label: {
                            Label(item.label, systemImage: item.symbol)
                                .font(.footnote.weight(.bold))
                                .foregroundStyle(tab == item ? .white : .secondary)
                                .padding(.horizontal, 12)
                                .padding(.vertical, 8)
                                .background(tab == item ? AnyShapeStyle(Theme.accent) : AnyShapeStyle(Color.secondary.opacity(0.12)),
                                            in: Capsule())
                        }
                        .buttonStyle(PressableStyle(scale: 0.95))
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
            }
            .background(Theme.paper)

            Group {
                switch tab {
                case .summary:
                    SummaryView(sessionID: sessionID, initialSummary: initialSummary, onSelectPage: onSelectPage)
                case .flashcards:
                    StudyLoader(sessionID: sessionID, kind: "flashcards", label: "플래시카드", as: [Flashcard].self) {
                        FlashcardsPane(sessionID: sessionID, cards: $0, onSelectPage: onSelectPage)
                    }
                case .mindmap:
                    StudyLoader(sessionID: sessionID, kind: "mindmap", label: "마인드맵", as: MindNode.self) {
                        MindmapPane(root: $0, onSelectPage: onSelectPage)
                    }
                case .concepts:
                    StudyLoader(sessionID: sessionID, kind: "concepts", label: "개념 메모", as: [Concept].self) {
                        ConceptsPane(concepts: $0, onSelectPage: onSelectPage)
                    }
                case .cloze:
                    StudyLoader(sessionID: sessionID, kind: "cloze", label: "암기", as: [ClozeItem].self, canGenerate: false) {
                        ClozePane(sessionID: sessionID, items: $0, onSelectPage: onSelectPage)
                    }
                case .tutor:
                    TutorPane(sessionID: sessionID, onSelectPage: onSelectPage)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Theme.paper)
        }
        .tint(Theme.accent)
        .fontDesign(.rounded)
    }
}

/// AI로 만드는 공부 도구: 없으면 만들기 버튼, 만드는 중이면 진행률, 다 되면 내용
private struct StudyLoader<Payload: Decodable, Content: View>: View {
    let sessionID: String
    let kind: String
    let label: String
    let type: Payload.Type
    var canGenerate = true
    let content: (Payload) -> Content

    @State private var response: StudyResponse<Payload>?
    @State private var errorMessage: String?

    init(sessionID: String, kind: String, label: String, as type: Payload.Type, canGenerate: Bool = true,
         @ViewBuilder content: @escaping (Payload) -> Content) {
        self.sessionID = sessionID
        self.kind = kind
        self.label = label
        self.type = type
        self.canGenerate = canGenerate
        self.content = content
    }

    var body: some View {
        Group {
            if let payload = response?.body, response?.status == "ready" {
                content(payload)
            } else if let errorMessage {
                ContentUnavailableView("불러오지 못했어요", systemImage: "wifi.slash", description: Text(errorMessage))
            } else if response?.status == "none" && canGenerate {
                VStack(spacing: 14) {
                    Image(systemName: "sparkles").font(.largeTitle).foregroundStyle(Theme.accent)
                    Text("이 강의로 \(label)을 만들어요").font(.headline)
                    Button { Task { await generate() } } label: {
                        Label("\(label) 만들기", systemImage: "sparkles").frame(maxWidth: 240).frame(height: 44)
                    }
                    .buttonStyle(.borderedProminent)
                }
                .frame(maxHeight: .infinity)
            } else {
                let progress = (response?.total ?? 0) > 0 ? " (\(response?.done ?? 0)/\(response?.total ?? 0)쪽)" : ""
                ProgressView("AI가 \(label) 만드는 중…\(progress)").frame(maxHeight: .infinity)
            }
        }
        .task(id: kind) { await poll() }
    }

    private func generate() async {
        do {
            try await APIClient.current().startStudy(sessionId: sessionID, kind: kind)
            response = nil
            await poll()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func poll() async {
        while !Task.isCancelled {
            do {
                let result = try await APIClient.current().study(sessionId: sessionID, kind: kind, as: Payload.self)
                response = result
                if result.status != "building" { return }
            } catch {
                errorMessage = error.localizedDescription
                return
            }
            try? await Task.sleep(for: .seconds(1.5))
        }
    }
}

private struct PageChip: View {
    let pageNo: Int?
    let onSelect: (Int) -> Void

    var body: some View {
        if let pageNo {
            Button("\(pageNo)쪽") { onSelect(pageNo) }
                .font(.caption.weight(.bold))
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .background(Theme.accent.opacity(0.1), in: Capsule())
        }
    }
}

// 플래시카드: 눌러서 뒤집기, 알아요/몰라요, 모르는 것만 다시

private struct FlashcardsPane: View {
    let sessionID: String
    let cards: [Flashcard]
    let onSelectPage: (Int) -> Void
    @State private var index = 0
    @State private var flipped = false
    @State private var onlyUnknown = false
    @State private var known: Set<Int> = []

    private var key: String { "flashcards.\(sessionID)" }
    private var deck: [Int] { cards.indices.filter { !onlyUnknown || !known.contains($0) } }

    var body: some View {
        VStack(spacing: 16) {
            if cards.isEmpty {
                Text("만들 카드가 없었어요.").foregroundStyle(.secondary)
            } else if deck.isEmpty {
                VStack(spacing: 10) {
                    Image(systemName: "checkmark.seal.fill").font(.system(size: 48)).foregroundStyle(.green)
                    Text("다 외웠어요!").font(.headline)
                    Button("처음부터") { known = []; save(); onlyUnknown = false; index = 0 }
                }
            } else {
                let i = deck[index % deck.count]
                HStack {
                    Text("\(index % deck.count + 1) / \(deck.count) · 알아요 \(known.count)").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button(onlyUnknown ? "전체 보기" : "모르는 것만") { onlyUnknown.toggle(); index = 0; flipped = false }
                        .font(.caption.weight(.bold))
                }
                ZStack {
                    face(cards[i].front, hint: "눌러서 뒤집기", color: AnnotationType.explanation.noteColor)
                        .opacity(flipped ? 0 : 1)
                        .rotation3DEffect(.degrees(flipped ? -180 : 0), axis: (0, 1, 0))
                    face(cards[i].back, hint: nil, color: Color(.secondarySystemBackground))
                        .opacity(flipped ? 1 : 0)
                        .rotation3DEffect(.degrees(flipped ? 0 : 180), axis: (0, 1, 0))
                }
                .frame(height: 240)
                .onTapGesture { withAnimation(.spring(response: 0.45, dampingFraction: 0.8)) { flipped.toggle() } }
                HStack {
                    PageChip(pageNo: cards[i].pageNo, onSelect: onSelectPage)
                    Spacer()
                    Button { known.remove(i); save(); next() } label: { Label("몰라요", systemImage: "xmark") }
                        .tint(AnnotationType.exam.inkColor)
                    Button { known.insert(i); save(); if !onlyUnknown { next() } else { flipped = false } } label: {
                        Label("알아요", systemImage: "checkmark")
                    }
                    .tint(.green)
                }
                .buttonStyle(.bordered)
                .sensoryFeedback(.selection, trigger: index)
            }
            Spacer()
        }
        .padding(18)
        .onAppear {
            known = Set((UserDefaults.standard.array(forKey: key) as? [Int]) ?? [])
        }
    }

    private func face(_ text: String, hint: String?, color: Color) -> some View {
        VStack(spacing: 10) {
            Text(text).font(.title3.weight(.bold)).multilineTextAlignment(.center)
            if let hint { Text(hint).font(.caption).foregroundStyle(.secondary) }
        }
        .padding(22)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(color, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: .black.opacity(0.1), radius: 10, y: 4)
    }

    private func next() {
        flipped = false
        index += 1
    }

    private func save() { UserDefaults.standard.set(Array(known), forKey: key) }
}

// 마인드맵: 가운데 주제 → 큰 가지 → 세부 (들여 쓴 나무 모양)

private struct MindmapPane: View {
    let root: MindNode
    let onSelectPage: (Int) -> Void

    var body: some View {
        ScrollView([.vertical, .horizontal]) {
            VStack(alignment: .leading, spacing: 10) {
                Text("가지를 누르면 그 쪽으로 가요.").font(.footnote).foregroundStyle(.secondary)
                node(root, depth: 0)
            }
            .padding(18)
        }
    }

    private func node(_ n: MindNode, depth: Int) -> AnyView {
        AnyView(VStack(alignment: .leading, spacing: 8) {
            Button { if let page = n.pageNo { onSelectPage(page) } } label: {
                HStack(spacing: 4) {
                    Text(n.label)
                    if let page = n.pageNo { Text("\(page)쪽").font(.caption2).foregroundStyle(Theme.accent) }
                }
                .font(depth == 0 ? .headline.weight(.heavy) : depth == 1 ? .subheadline.weight(.bold) : .subheadline)
                .foregroundStyle(depth == 0 ? .white : Color.primary)
                .padding(.horizontal, 12)
                .padding(.vertical, 7)
                .background(depth == 0 ? Theme.accent : depth == 1 ? AnnotationType.explanation.noteColor : Color(.secondarySystemBackground),
                            in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .fixedSize()
            }
            .buttonStyle(.plain)
            if let children = n.children, !children.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(children) { child in
                        HStack(alignment: .top, spacing: 0) {
                            Rectangle().fill(Theme.accent.opacity(0.3)).frame(width: 14, height: 2).padding(.top, 16)
                            node(child, depth: depth + 1)
                        }
                    }
                }
                .padding(.leading, 14)
                .overlay(alignment: .leading) { Rectangle().fill(Theme.accent.opacity(0.3)).frame(width: 2).padding(.bottom, 16) }
            }
        })
    }
}

// 개념 메모: 용어·뜻·예시, 찾기

private struct ConceptsPane: View {
    let concepts: [Concept]
    let onSelectPage: (Int) -> Void
    @State private var query = ""

    var body: some View {
        let shown = concepts.filter { query.isEmpty || "\($0.term) \($0.definition) \($0.example ?? "")".contains(query) }
        List {
            ForEach(shown, id: \.self) { concept in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(concept.term).font(.headline)
                        Spacer()
                        PageChip(pageNo: concept.pageNo, onSelect: onSelectPage)
                    }
                    Text(concept.definition).font(.subheadline)
                    if let example = concept.example, !example.isEmpty {
                        Label(example, systemImage: "lightbulb").font(.footnote).foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 4)
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .searchable(text: $query, prompt: "개념 찾기")
    }
}

// 암기: 빈칸을 눌러 답 보기, 외운 문장 체크

private struct ClozePane: View {
    let sessionID: String
    let items: [ClozeItem]
    let onSelectPage: (Int) -> Void
    @State private var revealed: Set<Int> = []
    @State private var done: Set<Int> = []

    private var key: String { "cloze.\(sessionID)" }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text("빈칸을 눌러 답을 확인하고, 외운 문장은 체크하세요. 시험·강조 필기가 먼저 나와요.")
                    .font(.footnote).foregroundStyle(.secondary)
                if items.isEmpty {
                    Text("빈칸으로 낼 용어가 있는 필기가 아직 없어요.").foregroundStyle(.secondary)
                }
                ForEach(Array(items.enumerated()), id: \.offset) { n, item in
                    VStack(alignment: .leading, spacing: 8) {
                        Button { withAnimation(.snappy) { _ = revealed.insert(n) } } label: {
                            sentence(item, shown: revealed.contains(n))
                                .multilineTextAlignment(.leading)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .buttonStyle(.plain)
                        HStack {
                            PageChip(pageNo: item.pageNo, onSelect: onSelectPage)
                            Spacer()
                            Button { if done.contains(n) { done.remove(n) } else { done.insert(n) }; save() } label: {
                                Label("외웠어요", systemImage: done.contains(n) ? "checkmark.circle.fill" : "circle")
                                    .font(.caption.weight(.bold))
                            }
                        }
                    }
                    .card(padding: 14)
                    .opacity(done.contains(n) ? 0.55 : 1)
                }
            }
            .padding(18)
        }
        .onAppear { done = Set((UserDefaults.standard.array(forKey: key) as? [Int]) ?? []) }
    }

    private func sentence(_ item: ClozeItem, shown: Bool) -> Text {
        let parts = item.text.components(separatedBy: "____")
        let blank = shown ? Text(" \(item.answer) ").foregroundColor(AnnotationType.exam.inkColor).bold()
                          : Text(" ______ ").foregroundColor(Theme.accent).bold()
        var text = item.important ? Text(Image(systemName: "star.fill")).foregroundColor(AnnotationType.exam.inkColor) + Text(" ") : Text("")
        for (i, part) in parts.enumerated() {
            text = text + Text(part)
            if i < parts.count - 1 { text = text + blank }
        }
        return text.font(.subheadline)
    }

    private func save() { UserDefaults.standard.set(Array(done), forKey: key) }
}

// AI 튜터: 강의 내용으로 대화, 답마다 근거 쪽

private struct TutorPane: View {
    let sessionID: String
    let onSelectPage: (Int) -> Void
    @State private var messages: [TutorMessage] = []
    @State private var input = ""
    @State private var thinking = false
    @State private var errorMessage: String?
    private let quick = ["이 강의 핵심 3가지 설명해 줘", "나한테 문제 하나 내 줘", "제일 헷갈리는 개념 쉽게 설명해 줘"]

    var body: some View {
        VStack(spacing: 8) {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        if messages.isEmpty {
                            Label("이 강의의 슬라이드와 교수님 설명을 아는 튜터예요. 모르는 걸 묻거나 문제를 내 달라고 해 보세요.",
                                  systemImage: "bubble.left.and.bubble.right")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                        ForEach(messages) { message in
                            bubble(message).id(message.id)
                        }
                        if thinking { ProgressView("생각하는 중…").font(.footnote) }
                    }
                    .padding(18)
                }
                .onChange(of: messages.count) { _, _ in
                    if let last = messages.last { withAnimation { proxy.scrollTo(last.id, anchor: .bottom) } }
                }
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack {
                    ForEach(quick, id: \.self) { q in
                        Button(q) { Task { await send(q) } }.font(.caption.weight(.bold)).buttonStyle(.bordered)
                    }
                }
                .padding(.horizontal, 16)
            }
            HStack {
                TextField("강의 내용으로 무엇이든 물어보세요", text: $input)
                    .textFieldStyle(.roundedBorder)
                    .submitLabel(.send)
                    .onSubmit { Task { await send(input) } }
                Button("보내기") { Task { await send(input) } }.buttonStyle(.borderedProminent).disabled(thinking)
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 10)
        }
        .alert("알림", isPresented: .constant(errorMessage != nil)) {
            Button("확인") { errorMessage = nil }
        } message: { Text(errorMessage ?? "") }
        .onAppear { load() }
    }

    private func bubble(_ message: TutorMessage) -> some View {
        let mine = message.role == "user"
        return HStack {
            if mine { Spacer(minLength: 40) }
            VStack(alignment: .leading, spacing: 6) {
                Text(message.content).font(.subheadline).foregroundStyle(mine ? .white : .primary)
                if !message.pages.isEmpty {
                    HStack { ForEach(message.pages, id: \.self) { PageChip(pageNo: $0, onSelect: onSelectPage) } }
                }
            }
            .padding(12)
            .background(mine ? AnyShapeStyle(Theme.accent) : AnyShapeStyle(Color(.secondarySystemBackground)),
                        in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            if !mine { Spacer(minLength: 40) }
        }
    }

    private func send(_ text: String) async {
        let question = text.trimmingCharacters(in: .whitespaces)
        guard !question.isEmpty, !thinking else { return }
        input = ""
        messages.append(TutorMessage(role: "user", content: question))
        thinking = true
        defer { thinking = false; save() }
        do {
            let reply = try await APIClient.current().tutor(sessionId: sessionID, messages: messages)
            messages.append(TutorMessage(role: "assistant", content: reply.answer, pages: reply.pages))
        } catch {
            messages.removeLast()
            errorMessage = error.localizedDescription
        }
    }

    private var key: String { "tutor.\(sessionID)" }

    private func load() {
        guard messages.isEmpty, let data = UserDefaults.standard.data(forKey: key) else { return }
        messages = (try? JSONDecoder().decode([TutorMessage].self, from: data)) ?? []
    }

    private func save() {
        if let data = try? JSONEncoder().encode(Array(messages.suffix(30))) { UserDefaults.standard.set(data, forKey: key) }
    }
}
