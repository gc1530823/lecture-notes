import SwiftUI

// 서버 JSON은 snake_case이고, APIClient의 디코더가 camelCase로 바꾼다.

struct Block: Codable, Identifiable, Hashable {
    let id: Int
    /// 페이지 크기 대비 0~1 좌표, 원점은 왼쪽 위
    let x: Double
    let y: Double
    let w: Double
    let h: Double
    let text: String
}

struct Page: Codable, Identifiable, Hashable {
    let id: Int
    let pageNo: Int
    let width: Double
    let height: Double
    let blocks: [Block]

    var aspectRatio: CGFloat { CGFloat(width / max(height, 1)) }
}

struct LectureDocument: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let pageCount: Int
    let keywords: [String]
    let pages: [Page]
}

enum AnnotationType: String, Codable, CaseIterable {
    case explanation, example, emphasis, exam, notice
    /// 교수님 발언이 아니라 AI가 덧붙인 배경지식·공부 팁
    case tip

    var label: String {
        switch self {
        case .explanation: "보충설명"
        case .example: "예시"
        case .emphasis: "강조"
        case .exam: "시험"
        case .notice: "공지"
        case .tip: "AI 팁"
        }
    }

    var color: Color {
        switch self {
        case .explanation: .blue
        case .example: .green
        case .emphasis: .orange
        case .exam: .red
        case .notice: .purple
        case .tip: .cyan
        }
    }

    var symbol: String {
        switch self {
        case .explanation: "text.bubble"
        case .example: "lightbulb"
        case .emphasis: "exclamationmark.circle"
        case .exam: "star.fill"
        case .notice: "megaphone"
        case .tip: "sparkles"
        }
    }
}

struct Annotation: Codable, Identifiable, Hashable {
    let id: Int
    let sessionId: String
    let pageNo: Int
    let blockId: Int?
    let type: AnnotationType
    var text: String
    let startMs: Int
    var editedByUser: Bool
    /// 어느 페이지인지 확실하지 않아 보류함에 있는 필기
    var pending: Bool = false

    enum CodingKeys: String, CodingKey {
        case id, sessionId, pageNo, blockId, type, text, startMs, editedByUser, pending
    }

    init(id: Int, sessionId: String, pageNo: Int, blockId: Int?, type: AnnotationType, text: String,
         startMs: Int, editedByUser: Bool, pending: Bool = false) {
        self.id = id
        self.sessionId = sessionId
        self.pageNo = pageNo
        self.blockId = blockId
        self.type = type
        self.text = text
        self.startMs = startMs
        self.editedByUser = editedByUser
        self.pending = pending
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
        sessionId = try c.decode(String.self, forKey: .sessionId)
        pageNo = try c.decode(Int.self, forKey: .pageNo)
        blockId = try c.decodeIfPresent(Int.self, forKey: .blockId)
        type = try c.decode(AnnotationType.self, forKey: .type)
        text = try c.decode(String.self, forKey: .text)
        startMs = try c.decode(Int.self, forKey: .startMs)
        editedByUser = try c.decode(Bool.self, forKey: .editedByUser)
        pending = try c.decodeIfPresent(Bool.self, forKey: .pending) ?? false
    }
}

struct LectureSession: Codable, Hashable {
    let id: String
    let documentId: String
    let status: String
}

struct SummaryResponse: Codable {
    let status: String
    let summary: LectureSummary?
}

struct LectureSummary: Codable, Hashable {
    let overview: String
    let pages: [PageSummary]
    let quiz: [QuizItem]
    /// 웹 검색으로 찾은 추가 자료 (예전 서버 응답에는 없을 수 있다)
    var tips: [WebTip]? = nil
}

struct WebTip: Codable, Hashable {
    let pageNo: Int
    let title: String
    let text: String
    let url: String
}

struct PageSummary: Codable, Hashable {
    let pageNo: Int
    let summary: String
}

struct QuizItem: Codable, Hashable {
    let pageNo: Int
    let question: String
    let choices: [String]
    let answerIndex: Int
    let explanation: String
}

/// 기기에 저장하는 강의자료: 서버 분석 결과 + 로컬 PDF 파일 + 지난 강의 목록
struct LocalDocument: Codable, Identifiable, Hashable {
    let document: LectureDocument
    let pdfFileName: String
    var sessions: [SavedSession]

    var id: String { document.id }
}

struct SavedSession: Codable, Identifiable, Hashable {
    let id: String
    let startedAt: Date
    let recordingFileName: String
}
