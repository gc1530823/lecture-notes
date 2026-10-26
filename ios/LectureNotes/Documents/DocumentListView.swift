import SwiftUI

struct DocumentListView: View {
    @EnvironmentObject private var store: DocumentStore
    @State private var showingImporter = false
    @State private var showingSettings = false
    @State private var uploading = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Group {
                if store.documents.isEmpty {
                    ContentUnavailableView {
                        Label("강의자료가 없어요", systemImage: "doc.richtext")
                    } description: {
                        Text("PDF 강의자료를 올리면, 강의를 녹음할 때 자료 위에 필기가 자동으로 써져요.")
                    } actions: {
                        Button("PDF 올리기") { showingImporter = true }
                            .buttonStyle(.borderedProminent)
                    }
                } else {
                    List {
                        ForEach(store.documents) { document in
                            NavigationLink(value: document) {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(document.document.title).font(.headline)
                                    Text("\(document.document.pageCount)쪽 · 강의 \(document.sessions.count)회")
                                        .font(.subheadline)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                        .onDelete { offsets in
                            offsets.map { store.documents[$0] }.forEach(store.delete)
                        }
                    }
                }
            }
            .navigationTitle("강의노트")
            .navigationDestination(for: LocalDocument.self) { document in
                DocumentDetailView(documentID: document.id)
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { showingSettings = true } label: { Image(systemName: "gearshape") }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showingImporter = true } label: { Image(systemName: "plus") }
                        .disabled(uploading)
                }
            }
            .fileImporter(isPresented: $showingImporter, allowedContentTypes: [.pdf]) { result in
                guard case let .success(url) = result else { return }
                Task { await importPDF(url) }
            }
            .overlay {
                if uploading {
                    ProgressView("강의자료 분석 중…")
                        .padding(24)
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                }
            }
            .sheet(isPresented: $showingSettings) { SettingsView() }
            .alert("오류", isPresented: .constant(errorMessage != nil)) {
                Button("확인") { errorMessage = nil }
            } message: {
                Text(errorMessage ?? "")
            }
        }
    }

    private func importPDF(_ url: URL) async {
        uploading = true
        defer { uploading = false }
        do {
            try await store.importPDF(from: url)
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

struct DocumentDetailView: View {
    @EnvironmentObject private var store: DocumentStore
    let documentID: String

    var body: some View {
        if let document = store.documents.first(where: { $0.id == documentID }) {
            List {
                Section {
                    NavigationLink {
                        LectureView(document: document, store: store, session: nil)
                    } label: {
                        Label("새 강의 녹음하기", systemImage: "record.circle")
                            .foregroundStyle(.red)
                    }
                }
                Section("지난 강의") {
                    if document.sessions.isEmpty {
                        Text("아직 녹음한 강의가 없어요").foregroundStyle(.secondary)
                    }
                    ForEach(document.sessions) { session in
                        NavigationLink {
                            LectureView(document: document, store: store, session: session)
                        } label: {
                            Text(session.startedAt.formatted(date: .abbreviated, time: .shortened))
                        }
                    }
                }
            }
            .navigationTitle(document.document.title)
        }
    }
}

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @AppStorage(APIClient.serverURLKey) private var serverURL = APIClient.defaultServerURL

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://192.168.0.10:8000", text: $serverURL)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("서버 주소")
                } footer: {
                    Text("시뮬레이터는 http://localhost:8000, 실제 iPhone은 같은 Wi-Fi에 있는 Mac의 IP 주소를 넣어 주세요.")
                }
            }
            .navigationTitle("설정")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("완료") { dismiss() } }
            }
        }
    }
}
