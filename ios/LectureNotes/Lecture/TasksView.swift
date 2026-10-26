import SwiftUI

extension TaskKind {
    var color: Color {
        switch self {
        case .inClass: Theme.record
        case .homework: Theme.accent
        case .report: Color(red: 0.05, green: 0.52, blue: 0.80)
        case .examPrep: Color(red: 0.93, green: 0.45, blue: 0.07)
        }
    }
}

/// 새 과제가 들어오면 강의 화면 위에서 내려오는 배너
struct TaskBanner: View {
    let task: LectureTask
    let onOpen: () -> Void
    let onClose: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: task.kind.symbol)
                .font(.headline)
                .foregroundStyle(.white)
                .frame(width: 38, height: 38)
                .background(task.kind.color.gradient, in: RoundedRectangle(cornerRadius: 11, style: .continuous))
                .symbolEffect(.bounce, value: task.id)
            VStack(alignment: .leading, spacing: 2) {
                Text("새 \(task.kind.label)\(task.dueText.isEmpty ? "" : " · \(task.dueText)")")
                    .font(.caption.weight(.heavy))
                    .foregroundStyle(task.kind.color)
                Text(task.title)
                    .font(.subheadline.weight(.bold))
                    .lineLimit(1)
            }
            Spacer(minLength: 4)
            Button(action: onOpen) {
                Text("바로 하기")
                    .font(.caption.weight(.heavy))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(task.kind.color, in: Capsule())
            }
            .buttonStyle(PressableStyle(scale: 0.92))
            Button(action: onClose) {
                Image(systemName: "xmark").font(.caption.weight(.bold)).foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(task.kind.color.opacity(0.35)))
        .shadow(color: .black.opacity(0.15), radius: 16, y: 8)
        .padding(.horizontal, 14)
    }
}

/// 이번 강의의 과제 목록
struct TasksSheet: View {
    @ObservedObject var model: LectureViewModel
    @Environment(\.dismiss) private var dismiss
    var startWith: LectureTask?
    @State private var path: [LectureTask] = []

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(spacing: 12) {
                    if model.tasks.isEmpty {
                        EmptyNote(message: "교수님이 과제를 내면 여기에 자동으로 모여요")
                    }
                    ForEach(model.tasks) { task in
                        NavigationLink(value: task) { TaskRow(task: task) }
                            .buttonStyle(PressableStyle(scale: 0.98))
                    }
                }
                .padding(18)
            }
            .background(Theme.paper.ignoresSafeArea())
            .navigationTitle("이번 강의 과제")
            .navigationBarTitleDisplayMode(.inline)
            .navigationDestination(for: LectureTask.self) { task in
                TaskDetailView(model: model, taskID: task.id)
            }
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("닫기") { dismiss() } } }
            .onAppear { if let startWith, path.isEmpty { path = [startWith] } }
        }
        .fontDesign(.rounded)
        .tint(Theme.accent)
    }
}

private struct TaskRow: View {
    let task: LectureTask

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: task.done ? "checkmark.circle.fill" : task.kind.symbol)
                .font(.headline)
                .foregroundStyle(task.done ? Color.green : task.kind.color)
                .frame(width: 36, height: 36)
                .background((task.done ? Color.green : task.kind.color).opacity(0.12), in: Circle())
            VStack(alignment: .leading, spacing: 3) {
                Text(task.title)
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(Color.primary)
                    .strikethrough(task.done)
                Text([task.kind.label, task.dueText].filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if task.draft != nil {
                Image(systemName: "sparkles").foregroundStyle(Theme.accent)
            }
            Image(systemName: "chevron.right").font(.footnote.weight(.bold)).foregroundStyle(.tertiary)
        }
        .card(padding: 12)
    }
}

/// 과제 하나: 요구사항 → "AI와 바로 하기" → 체크리스트·개요·고칠 수 있는 초안
struct TaskDetailView: View {
    @ObservedObject var model: LectureViewModel
    let taskID: Int
    @State private var drafting = false
    @State private var text = ""
    @State private var checked: Set<Int> = []
    @State private var copied = false

    private var task: LectureTask? { model.tasks.first { $0.id == taskID } }

    var body: some View {
        ScrollView {
            if let task {
                VStack(alignment: .leading, spacing: 18) {
                    header(task)
                    if let draft = task.draft {
                        result(task, draft)
                            .transition(.move(edge: .bottom).combined(with: .opacity))
                    } else {
                        draftButton(task)
                    }
                }
                .padding(18)
                .animation(.spring(response: 0.5, dampingFraction: 0.8), value: task.draft)
            }
        }
        .background(Theme.paper.ignoresSafeArea())
        .navigationTitle(task?.kind.label ?? "과제")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { if let draft = task?.draft, text.isEmpty { text = draft.draft } }
    }

    private func header(_ task: LectureTask) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Label(task.kind.label, systemImage: task.kind.symbol)
                if !task.dueText.isEmpty {
                    Text("·")
                    Label(task.dueText, systemImage: "clock")
                }
            }
            .font(.caption.weight(.heavy))
            .foregroundStyle(task.kind.color)
            Text(task.title).font(.title3.weight(.bold))
            Text(task.instructions).font(.subheadline).foregroundStyle(.secondary)
            if let page = task.pageNo {
                Text("\(page)쪽 설명 중에 나온 과제").font(.caption2).foregroundStyle(.tertiary)
            }
            Button {
                Task { await model.setDone(task, !task.done) }
            } label: {
                Label(task.done ? "완료함" : "완료 표시", systemImage: task.done ? "checkmark.circle.fill" : "circle")
                    .font(.footnote.weight(.bold))
                    .foregroundStyle(task.done ? Color.green : Color.secondary)
                    .contentTransition(.symbolEffect(.replace))
            }
            .sensoryFeedback(.success, trigger: task.done)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    private func draftButton(_ task: LectureTask) -> some View {
        Button {
            drafting = true
            Task {
                if let updated = await model.draft(task) { text = updated.draft?.draft ?? "" }
                drafting = false
            }
        } label: {
            HStack(spacing: 10) {
                if drafting {
                    ProgressView().tint(.white)
                    Text("오늘 강의 내용으로 만드는 중…")
                } else {
                    Image(systemName: "sparkles")
                    Text("AI와 바로 하기")
                }
            }
            .font(.headline.weight(.bold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .frame(height: 56)
            .background(Theme.accent.gradient, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .shadow(color: Theme.accent.opacity(0.35), radius: 12, y: 6)
        }
        .buttonStyle(PressableStyle(scale: 0.97))
        .disabled(drafting)
    }

    @ViewBuilder
    private func result(_ task: LectureTask, _ draft: TaskDraft) -> some View {
        section("요구사항 체크리스트", systemImage: "checklist")
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Array(draft.checklist.enumerated()), id: \.offset) { index, item in
                Button {
                    withAnimation(.snappy) {
                        if checked.contains(index) { checked.remove(index) } else { checked.insert(index) }
                    }
                } label: {
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: checked.contains(index) ? "checkmark.square.fill" : "square")
                            .foregroundStyle(checked.contains(index) ? Color.green : Color.secondary)
                            .contentTransition(.symbolEffect(.replace))
                        Text(item)
                            .font(.subheadline)
                            .foregroundStyle(Color.primary)
                            .strikethrough(checked.contains(index))
                            .multilineTextAlignment(.leading)
                        Spacer(minLength: 0)
                    }
                }
                .buttonStyle(.plain)
            }
        }
        .card()

        section("개요", systemImage: "list.number")
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(draft.outline.enumerated()), id: \.offset) { index, item in
                HStack(alignment: .top, spacing: 10) {
                    Text("\(index + 1)")
                        .font(.caption.weight(.heavy))
                        .foregroundStyle(Theme.accent)
                        .frame(width: 22, height: 22)
                        .background(Theme.accent.opacity(0.12), in: Circle())
                    Text(item).font(.subheadline)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()

        HStack {
            section("초안 (바로 고쳐 쓰세요)", systemImage: "pencil.and.scribble")
            Spacer()
            Button {
                UIPasteboard.general.string = text
                withAnimation(.snappy) { copied = true }
                Task {
                    try? await Task.sleep(for: .seconds(1.5))
                    withAnimation(.snappy) { copied = false }
                }
            } label: {
                Label(copied ? "복사됨" : "복사", systemImage: copied ? "checkmark" : "doc.on.doc")
                    .font(.caption.weight(.bold))
                    .contentTransition(.symbolEffect(.replace))
            }
            .sensoryFeedback(.success, trigger: copied)
            ShareLink(item: text) { Image(systemName: "square.and.arrow.up").font(.caption.weight(.bold)) }
        }
        TextEditor(text: $text)
            .font(.system(.subheadline, design: .rounded))
            .scrollContentBackground(.hidden)
            .frame(minHeight: 260)
            .padding(12)
            .background(Theme.card, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .shadow(color: .black.opacity(0.06), radius: 10, y: 4)

        HStack(spacing: 6) {
            Text("근거:")
            ForEach(draft.sources, id: \.self) { page in
                Text("\(page)쪽")
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(Theme.accent.opacity(0.12), in: Capsule())
            }
        }
        .font(.caption.weight(.bold))
        .foregroundStyle(Theme.accent)

        Label("AI가 만든 초안이에요. 수업마다 AI 사용 규칙이 다르니 확인하고, 본인 말로 고쳐서 제출하세요.",
              systemImage: "exclamationmark.shield")
            .font(.caption)
            .foregroundStyle(.secondary)
    }

    private func section(_ title: String, systemImage: String) -> some View {
        Label(title, systemImage: systemImage).font(.headline.weight(.bold))
    }
}
