import Foundation
import PDFKit

/// 기기에 저장한 강의자료 목록. PDF 원본과 녹음 파일은 앱의 Documents 폴더에 둔다.
@MainActor
final class DocumentStore: ObservableObject {
    @Published private(set) var documents: [LocalDocument] = []

    private let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    private var indexURL: URL { root.appending(path: "documents.json") }

    init(demo: Bool = false) {
        if demo {
            DemoData.writePDF(to: root.appending(path: DemoData.pdfFileName))
            documents = [DemoData.document]
        } else {
            load()
        }
    }

    func pdfURL(for document: LocalDocument) -> URL {
        root.appending(path: document.pdfFileName)
    }

    func recordingURL(for session: SavedSession) -> URL {
        root.appending(path: session.recordingFileName)
    }

    func pdf(for document: LocalDocument) -> PDFDocument? {
        PDFDocument(url: pdfURL(for: document))
    }

    /// 파일 앱에서 고른 PDF를 복사하고 서버에 올려 분석한다.
    func importPDF(from pickedURL: URL) async throws {
        let accessing = pickedURL.startAccessingSecurityScopedResource()
        defer { if accessing { pickedURL.stopAccessingSecurityScopedResource() } }

        let fileName = "\(UUID().uuidString).pdf"
        let localURL = root.appending(path: fileName)
        try FileManager.default.copyItem(at: pickedURL, to: localURL)

        do {
            let title = pickedURL.deletingPathExtension().lastPathComponent
            let document = try await APIClient.current().uploadDocument(pdfURL: localURL, title: title)
            documents.insert(LocalDocument(document: document, pdfFileName: fileName, sessions: []), at: 0)
            save()
        } catch {
            try? FileManager.default.removeItem(at: localURL)
            throw error
        }
    }

    func newSession(id: String, for documentID: String) -> SavedSession {
        let session = SavedSession(id: id, startedAt: Date(), recordingFileName: "\(id).m4a")
        if let index = documents.firstIndex(where: { $0.id == documentID }) {
            documents[index].sessions.insert(session, at: 0)
            save()
        }
        return session
    }

    func delete(_ document: LocalDocument) {
        try? FileManager.default.removeItem(at: pdfURL(for: document))
        document.sessions.forEach { try? FileManager.default.removeItem(at: recordingURL(for: $0)) }
        documents.removeAll { $0.id == document.id }
        save()
    }

    private func load() {
        guard let data = try? Data(contentsOf: indexURL) else { return }
        documents = (try? JSONDecoder().decode([LocalDocument].self, from: data)) ?? []
    }

    private func save() {
        guard let data = try? JSONEncoder().encode(documents) else { return }
        try? data.write(to: indexURL, options: .atomic)
    }
}
