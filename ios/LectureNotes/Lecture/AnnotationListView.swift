import SwiftUI

/// 현재 페이지의 필기를 포스트잇 보드(2열)로 보여 준다. 번호는 페이지 위 깃발과 같다.
struct AnnotationBoardView: View {
    let annotations: [Annotation]
    let latestID: Int?
    let isRecording: Bool
    @Binding var selectedID: Int?
    let onEdit: (Annotation) -> Void
    let onDelete: (Annotation) -> Void
    var canPlay = false
    var beyondIDs: Set<Int> = []
    var onPlay: (Annotation) -> Void = { _ in }

    private let columns = [GridItem(.flexible(), spacing: 14), GridItem(.flexible(), spacing: 14)]

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVGrid(columns: columns, alignment: .leading, spacing: 18) {
                    ForEach(Array(annotations.enumerated()), id: \.element.id) { index, annotation in
                        Button {
                            selectedID = selectedID == annotation.id ? nil : annotation.id
                        } label: {
                            StickyNote(annotation: annotation, number: index + 1,
                                       isSelected: selectedID == annotation.id, isPreview: annotation.id < 0,
                                       isBeyondSlides: beyondIDs.contains(annotation.id))
                        }
                        .buttonStyle(PressableStyle())
                        .overlay(alignment: .bottomTrailing) {
                            if canPlay && annotation.id > 0 {
                                Button { onPlay(annotation) } label: {
                                    Label(annotation.startMs.clockText, systemImage: "play.fill")
                                        .font(.caption.weight(.heavy).monospacedDigit())
                                        .foregroundStyle(Theme.accent)
                                        .padding(.horizontal, 10)
                                        .padding(.vertical, 5)
                                        .background(.background, in: Capsule())
                                        .shadow(color: .black.opacity(0.12), radius: 4, y: 2)
                                }
                                .buttonStyle(PressableStyle(scale: 0.92))
                                .offset(x: -6, y: 10)
                                .accessibilityLabel("이 필기 때 녹음 듣기")
                            }
                        }
                        .id(annotation.id)
                        .transition(.stickOn)
                        .contextMenu {
                            if annotation.id > 0 {
                                Button("수정", systemImage: "pencil") { onEdit(annotation) }
                                Button("삭제", systemImage: "trash", role: .destructive) { onDelete(annotation) }
                            }
                        }
                    }
                }
                .padding(.horizontal, 18)
                .padding(.top, 14)
                .padding(.bottom, 24)

                if annotations.isEmpty {
                    EmptyNote(message: isRecording
                              ? "교수님 설명을 듣고 있어요.\n필기가 여기에 붙어요."
                              : "이 페이지에는 아직 필기가 없어요")
                        .padding(.horizontal, 18)
                        .transition(.opacity)
                }
            }
            .scrollIndicators(.hidden)
            .onChange(of: selectedID) { _, id in
                guard let id else { return }
                withAnimation(.spring(response: 0.45, dampingFraction: 0.8)) { proxy.scrollTo(id, anchor: .center) }
            }
            .onChange(of: latestID) { _, id in
                guard let id, annotations.contains(where: { $0.id == id }) else { return }
                withAnimation(.spring(response: 0.5, dampingFraction: 0.85)) { proxy.scrollTo(id, anchor: .bottom) }
            }
        }
    }
}

struct AnnotationEditSheet: View {
    @Environment(\.dismiss) private var dismiss
    let annotation: Annotation
    let onSave: (String) -> Void
    @State private var text: String
    @FocusState private var focused: Bool

    init(annotation: Annotation, onSave: @escaping (String) -> Void) {
        self.annotation = annotation
        self.onSave = onSave
        _text = State(initialValue: annotation.text)
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 12) {
                Label(annotation.type.label, systemImage: annotation.type.symbol)
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(annotation.type.inkColor)
                TextEditor(text: $text)
                    .font(.system(.body, design: .rounded).weight(.medium))
                    .foregroundStyle(Theme.noteInk)
                    .scrollContentBackground(.hidden)
                    .focused($focused)
            }
            .padding(20)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(annotation.type.noteColor.ignoresSafeArea())
            .navigationTitle("필기 수정")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("저장") {
                        onSave(text)
                        dismiss()
                    }
                    .fontWeight(.bold)
                    .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .onAppear { focused = true }
        }
        .presentationDetents([.medium])
        .presentationCornerRadius(24)
    }
}
