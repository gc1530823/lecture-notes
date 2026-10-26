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

    var label: String {
        switch self {
        case .explanation: "보충설명"
        case .example: "예시"
        case .emphasis: "강조"
        case .exam: "시험"
        case .notice: "공지"
        }
    }

    var color: Color {
        switch self {
        case .explanation: .blue
        case .example: .green
        case .emphasis: .orange
        case .exam: .red
        case .notice: .purple
        }
    }

    var symbol: String {
        switch self {
        case .explanation: "text.bubble"
        case .example: "lightbulb"
        case .emphasis: "exclamationmark.circle"
        case .exam: "star.fill"
        case .notice: "megaphone"
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
