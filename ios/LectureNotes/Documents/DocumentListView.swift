import SwiftUI

struct DocumentListView: View {
    @EnvironmentObject private var store: DocumentStore
    @State private var showingImporter = false
    @State private var showingSettings = false
    @State private var uploading = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                if store.documents.isEmpty {
                    emptyState
                } else {
                    LazyVStack(spacing: 14) {
                        ForEach(Array(store.documents.enumerated()), id: \.element.id) { index, document in
                            NavigationLink(value: document) {
                                DocumentCard(document: document, store: store)
                            }
                            .buttonStyle(PressableStyle(scale: 0.97))
                            .contextMenu {
                                Button("삭제", systemImage: "trash", role: .destructive) {
                                    withAnimation(.snappy) { store.delete(document) }
                                }
                            }
                            .transition(.move(edge: .top).combined(with: .opacity))
                        }
                    }
                    .padding(.horizontal, 18)
                    .padding(.top, 6)
                    .padding(.bottom, 100)
                }
            }
            .background(Theme.paper.ignoresSafeArea())
            .navigationTitle("강의노트")
            .navigationDestination(for: LocalDocument.self) { document in
                DocumentDetailView(documentID: document.id)
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { showingSettings = true } label: { Image(systemName: "gearshape") }
                }
            }
            .overlay(alignment: .bottom) {
                if !store.documents.isEmpty { addButton.padding(.bottom, 12) }
            }
            .fileImporter(isPresented: $showingImporter, allowedContentTypes: [.pdf]) { result in
                guard case let .success(url) = result else { return }
                Task { await importPDF(url) }
            }
            .overlay {
                if uploading { UploadingOverlay().transition(.opacity) }
            }
            .animation(.easeInOut(duration: 0.2), value: uploading)
            .sheet(isPresented: $showingSettings) { SettingsView() }
            .alert("오류", isPresented: .constant(errorMessage != nil)) {
                Button("확인") { errorMessage = nil }
            } message: {
                Text(errorMessage ?? "")
            }
        }
        .tint(Theme.accent)
        .fontDesign(.rounded)
    }

    private var addButton: some View {
        Button { showingImporter = true } label: {
            Label("강의자료 올리기", systemImage: "plus")
                .font(.system(.subheadline, design: .rounded).weight(.bold))
                .foregroundStyle(.white)
                .padding(.horizontal, 22)
                .frame(height: 50)
                .background(Theme.accent.gradient, in: Capsule())
                .shadow(color: Theme.accent.opacity(0.35), radius: 12, y: 6)
        }
        .buttonStyle(PressableStyle())
        .disabled(uploading)
    }

    private var emptyState: some View {
        VStack(spacing: 22) {
            ZStack {
                StickyNote(annotation: Annotation(id: 2, sessionId: "", pageNo: 1, blockId: nil, type: .exam,
                                                  text: "시험에 나온다고 한 부분은 빨간 포스트잇", startMs: 0, editedByUser: false),
                           number: 2)
                    .frame(width: 170)
                    .offset(x: 78, y: 52)
                StickyNote(annotation: Annotation(id: 1, sessionId: "", pageNo: 1, blockId: nil, type: .explanation,
                                                  text: "교수님 설명이 자료 옆에 자동으로 붙어요", startMs: 0, editedByUser: false),
                           number: 1)
                    .frame(width: 170)
                    .offset(x: -70, y: -36)
            }
            .frame(height: 250)
            .phaseAnimator([false, true]) { notes, up in notes.offset(y: up ? -4 : 4) } animation: { _ in .easeInOut(duration: 2) }

            VStack(spacing: 8) {
                Text("첫 강의자료를 올려 보세요")
                    .font(.title3.weight(.bold))
                Text("PDF를 올리고 녹음을 시작하면\n설명이 해당 문단 옆에 필기로 붙어요.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            addButton
        }
        .padding(.top, 60)
        .frame(maxWidth: .infinity)
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

/// 강의자료 카드: 첫 페이지 썸네일 + 제목 + 강의 횟수
private struct DocumentCard: View {
    let document: LocalDocument
    let store: DocumentStore
    @State private var thumbnail: UIImage?

    var body: some View {
        HStack(spacing: 14) {
            ZStack {
                RoundedRectangle(cornerRadius: 10, style: .continuous).fill(.white)
                if let thumbnail {
                    Image(uiImage: thumbnail).resizable().scaledToFit()
                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                        .transition(.opacity)
                }
            }
            .frame(width: 104, height: 66)
            .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(.black.opacity(0.06)))
            .shadow(color: .black.opacity(0.08), radius: 4, y: 2)

            VStack(alignment: .leading, spacing: 6) {
                Text(document.document.title)
                    .font(.headline)
                    .foregroundStyle(.primary)
                    .lineLimit(2)
                HStack(spacing: 10) {
                    Label("\(document.document.pageCount)쪽", systemImage: "doc.text")
                    Label("강의 \(document.sessions.count)회", systemImage: "waveform")
                }
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                if let last = document.sessions.first {
                    Text("최근 \(last.startedAt.formatted(.relative(presentation: .named)))")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right")
                .font(.footnote.weight(.bold))
                .foregroundStyle(.tertiary)
        }
        .card(padding: 12)
        .task {
            let image = await PageRenderer.shared.image(for: store.pdf(for: document), pageIndex: 0, width: 400)
            withAnimation(.easeOut(duration: 0.25)) { thumbnail = image }
        }
    }
}

private struct UploadingOverlay: View {
    var body: some View {
        ZStack {
            Color.black.opacity(0.15).ignoresSafeArea()
            VStack(spacing: 14) {
                Image(systemName: "doc.viewfinder")
                    .font(.system(size: 34, weight: .semibold))
                    .foregroundStyle(Theme.accent)
                    .symbolEffect(.pulse, options: .repeating)
                Text("강의자료 분석 중…")
                    .font(.subheadline.weight(.semibold))
                Text("문단 위치와 전문용어를 찾고 있어요")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(28)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        }
    }
}

struct DocumentDetailView: View {
    @EnvironmentObject private var store: DocumentStore
    let documentID: String
    @State private var thumbnail: UIImage?

    var body: some View {
        if let document = store.documents.first(where: { $0.id == documentID }) {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 16, style: .continuous).fill(.white)
                        if let thumbnail {
                            Image(uiImage: thumbnail).resizable().scaledToFit()
                                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                        }
                    }
                    .aspectRatio(document.document.pages.first?.aspectRatio ?? 16 / 9, contentMode: .fit)
                    .shadow(color: .black.opacity(0.12), radius: 14, y: 6)

                    NavigationLink {
                        LectureView(document: document, store: store, session: nil)
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "mic.fill")
                            Text("새 강의 녹음하기")
                        }
                        .font(.system(.headline, design: .rounded).weight(.bold))
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 56)
                        .background(Theme.record.gradient, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                        .shadow(color: Theme.record.opacity(0.35), radius: 12, y: 6)
                    }
                    .buttonStyle(PressableStyle(scale: 0.97))

                    NavigationLink {
                        ExamMapView(document: document)
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: "scope")
                                .font(.headline.weight(.bold))
                                .foregroundStyle(AnnotationType.exam.inkColor)
                                .frame(width: 36, height: 36)
                                .background(AnnotationType.exam.inkColor.opacity(0.12), in: Circle())
                            VStack(alignment: .leading, spacing: 2) {
                                Text("시험 예상 지도")
                                    .font(.subheadline.weight(.semibold))
                                    .foregroundStyle(.primary)
                                Text("교수님이 강조하고 시험에 나온다고 한 곳을 표시하고 예상 문제를 만들어요")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .multilineTextAlignment(.leading)
                            }
                            Spacer()
                            Image(systemName: "chevron.right").font(.footnote.weight(.bold)).foregroundStyle(.tertiary)
                        }
                        .card(padding: 12)
                    }
                    .buttonStyle(PressableStyle(scale: 0.97))

                    Text("지난 강의")
                        .font(.system(.title3, design: .rounded).weight(.bold))
                        .padding(.top, 4)

                    if document.sessions.isEmpty {
                        EmptyNote(message: "아직 녹음한 강의가 없어요")
                    }
                    ForEach(Array(document.sessions.enumerated()), id: \.element.id) { index, session in
                        NavigationLink {
                            LectureView(document: document, store: store, session: session)
                        } label: {
                            HStack(spacing: 12) {
                                Text("\(document.sessions.count - index)")
                                    .font(.system(.subheadline, design: .rounded).weight(.heavy))
                                    .foregroundStyle(Theme.accent)
                                    .frame(width: 36, height: 36)
                                    .background(Theme.accent.opacity(0.12), in: Circle())
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("\(document.sessions.count - index)회차 강의")
                                        .font(.subheadline.weight(.semibold))
                                        .foregroundStyle(.primary)
                                    Text(session.startedAt.formatted(date: .abbreviated, time: .shortened))
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                Image(systemName: "chevron.right").font(.footnote.weight(.bold)).foregroundStyle(.tertiary)
                            }
                            .card(padding: 12)
                        }
                        .buttonStyle(PressableStyle(scale: 0.97))
                    }
                }
                .padding(18)
            }
            .background(Theme.paper.ignoresSafeArea())
            .navigationTitle(document.document.title)
            .navigationBarTitleDisplayMode(.inline)
            .fontDesign(.rounded)
            .task {
                let image = await PageRenderer.shared.image(for: store.pdf(for: document), pageIndex: 0, width: 900)
                withAnimation(.easeOut(duration: 0.25)) { thumbnail = image }
            }
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
