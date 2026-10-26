import SwiftUI

/// 현재 페이지의 필기 목록. 번호는 페이지 위 배지와 같다.
struct AnnotationListView: View {
    let annotations: [Annotation]
    let latestID: Int?
    @Binding var selectedID: Int?
    let onEdit: (Annotation) -> Void
    let onDelete: (Annotation) -> Void

    var body: some View {
        ScrollViewReader { proxy in
            List {
                if annotations.isEmpty {
                    Text("이 페이지에는 아직 필기가 없어요")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .listRowSeparator(.hidden)
                }
                ForEach(Array(annotations.enumerated()), id: \.element.id) { index, annotation in
                    AnnotationRow(number: index + 1, annotation: annotation,
                                  isSelected: selectedID == annotation.id)
                        .id(annotation.id)
                        .contentShape(Rectangle())
                        .onTapGesture { selectedID = annotation.id }
                        .swipeActions {
                            Button("삭제", role: .destructive) { onDelete(annotation) }
                            Button("수정") { onEdit(annotation) }.tint(.blue)
                        }
                        .contextMenu {
                            Button("수정", systemImage: "pencil") { onEdit(annotation) }
                            Button("삭제", systemImage: "trash", role: .destructive) { onDelete(annotation) }
                        }
                }
            }
            .listStyle(.plain)
            .onChange(of: selectedID) { _, id in
                guard let id else { return }
                withAnimation { proxy.scrollTo(id, anchor: .center) }
            }
            .onChange(of: latestID) { _, id in
                guard let id, annotations.contains(where: { $0.id == id }) else { return }
                withAnimation { proxy.scrollTo(id, anchor: .bottom) }
            }
        }
    }
}

private struct AnnotationRow: View {
    let number: Int
    let annotation: Annotation
    let isSelected: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Text("\(number)")
                .font(.caption2.bold())
                .foregroundStyle(.white)
                .frame(width: 20, height: 20)
                .background(annotation.type.color, in: Circle())
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 4) {
                    Label(annotation.type.label, systemImage: annotation.type.symbol)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(annotation.type.color)
                    if annotation.editedByUser {
                        Text("· 수정함").font(.caption).foregroundStyle(.secondary)
                    }
                }
                Text(annotation.text).font(.subheadline)
            }
        }
        .padding(.vertical, 4)
        .listRowBackground(isSelected ? annotation.type.color.opacity(0.08) : Color.clear)
    }
}

struct AnnotationEditSheet: View {
    @Environment(\.dismiss) private var dismiss
    let annotation: Annotation
    let onSave: (String) -> Void
    @State private var text: String

    init(annotation: Annotation, onSave: @escaping (String) -> Void) {
        self.annotation = annotation
        self.onSave = onSave
        _text = State(initialValue: annotation.text)
    }

    var body: some View {
        NavigationStack {
            TextEditor(text: $text)
                .padding()
                .navigationTitle("필기 수정")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("저장") {
                            onSave(text)
                            dismiss()
                        }
                        .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
        }
        .presentationDetents([.medium])
    }
}
