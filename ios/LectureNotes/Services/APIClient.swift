import Foundation

enum APIError: LocalizedError {
    case badServerURL
    case server(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .badServerURL: "서버 주소가 올바르지 않습니다. 설정에서 확인해 주세요."
        case let .server(status, message): "서버 오류 (\(status)): \(message)"
        }
    }
}

/// FastAPI 서버(REST) 호출. 실시간 통신은 LectureSocket이 맡는다.
struct APIClient {
    static let serverURLKey = "serverURL"
    static let defaultServerURL = "http://localhost:8000"

    let baseURL: URL

    static func current() throws -> APIClient {
        let raw = UserDefaults.standard.string(forKey: serverURLKey) ?? defaultServerURL
        guard let url = URL(string: raw.trimmingCharacters(in: .whitespaces)), url.scheme != nil else {
            throw APIError.badServerURL
        }
        return APIClient(baseURL: url)
    }

    static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    // 강의자료

    func uploadDocument(pdfURL: URL, title: String) async throws -> LectureDocument {
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()
        func append(_ string: String) { body.append(Data(string.utf8)) }

        append("--\(boundary)\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n\(title)\r\n")
        append("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"lecture.pdf\"\r\n")
        append("Content-Type: application/pdf\r\n\r\n")
        body.append(try Data(contentsOf: pdfURL))
        append("\r\n--\(boundary)--\r\n")

        var request = URLRequest(url: baseURL.appending(path: "documents"))
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 120
        let (data, response) = try await URLSession.shared.upload(for: request, from: body)
        return try decode(data, response)
    }

    // 강의 세션

    func createSession(documentId: String) async throws -> LectureSession {
        try await send("POST", "sessions", json: ["document_id": documentId])
    }

    func endSession(id: String) async throws -> LectureSession {
        try await send("POST", "sessions/\(id)/end")
    }

    func summary(sessionId: String) async throws -> SummaryResponse {
        try await send("GET", "sessions/\(sessionId)/summary")
    }

    func annotations(sessionId: String) async throws -> [Annotation] {
        try await send("GET", "sessions/\(sessionId)/annotations")
    }

    func streamURL(sessionId: String) -> URL {
        var components = URLComponents(url: baseURL.appending(path: "sessions/\(sessionId)/stream"),
                                       resolvingAgainstBaseURL: false)!
        components.scheme = baseURL.scheme == "https" ? "wss" : "ws"
        return components.url!
    }

    // 필기 편집

    func updateAnnotation(id: Int, text: String) async throws -> Annotation {
        try await send("PATCH", "annotations/\(id)", json: ["text": text])
    }

    func deleteAnnotation(id: Int) async throws {
        var request = URLRequest(url: baseURL.appending(path: "annotations/\(id)"))
        request.httpMethod = "DELETE"
        let (data, response) = try await URLSession.shared.data(for: request)
        try check(data, response)
    }

    // 공통

    private func send<T: Decodable>(_ method: String, _ path: String, json: [String: Any]? = nil) async throws -> T {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = method
        if let json {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: json)
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        return try decode(data, response)
    }

    private func decode<T: Decodable>(_ data: Data, _ response: URLResponse) throws -> T {
        try check(data, response)
        return try Self.decoder.decode(T.self, from: data)
    }

    private func check(_ data: Data, _ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) else { return }
        let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]
        throw APIError.server(status: http.statusCode, message: (detail as? String) ?? "알 수 없는 오류")
    }
}
