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
    /// 노트 모드에서는 그 주제의 제목 (AI가 붙인다). 강의자료 페이지는 슬라이드 글자.
    var text: String? = nil

    var aspectRatio: CGFloat { CGFloat(width / max(height, 1)) }
}

struct LectureDocument: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let pageCount: Int
    let keywords: [String]
    let pages: [Page]
    /// "slides" = 강의자료 PDF, "notebook" = 자료 없는 수업의 노트
    var kind: String? = nil

    var isNotebook: Bool { kind == "notebook" }
}

enum AnnotationType: String, Codable, CaseIterable {
    case explanation, example, emphasis, exam, notice
    /// 교수님 발언이 아니라 AI가 덧붙인 배경지식·공부 팁
    case tip
    /// 수업 중 "방금 뭐라고?"로 물어본 질문과 답
    case qa

    var label: String {
        switch self {
        case .explanation: "보충설명"
        case .example: "예시"
        case .emphasis: "강조"
        case .exam: "시험"
        case .notice: "공지"
        case .tip: "AI 팁"
        case .qa: "질문"
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
        case .qa: .pink
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
        case .qa: "hand.raised.fill"
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
        // 서버에 새 종류가 생겨도 앱이 멈추지 않게, 모르는 종류는 보충설명으로 보여 준다
        type = (try? c.decode(AnnotationType.self, forKey: .type)) ?? .explanation
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

/// 시험 예상 지도 (GET /documents/{id}/exam-map)
struct ExamMap: Codable, Hashable {
    let lectures: Int
    let pages: [ExamPageScore]
    let top: [Int]
    let questions: [ExamPageQuestions]
    let job: ExamJob
}

struct ExamPageScore: Codable, Hashable {
    let pageNo: Int
    let score: Double
    /// high, medium, low
    let level: String
    let reasons: [String]
}

struct ExamPageQuestions: Codable, Hashable {
    let pageNo: Int
    let questions: [PredictedQuestion]
    /// 문제를 만든 뒤 강의 내용이 바뀌었는지
    let stale: Bool
}

struct PredictedQuestion: Codable, Hashable {
    let question: String
    let answer: String
    let reason: String
}

struct ExamJob: Codable, Hashable {
    let status: String
    let done: Int
    let total: Int
}

/// 강의 정리 PDF 만들기 상태 (status: none, building, ready, failed)
struct NotesPDFStatus: Codable, Hashable {
    let status: String
    let done: Int
    let total: Int
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

/// 수업 중에 교수님이 낸 과제
enum TaskKind: String, Codable, CaseIterable {
    case inClass = "in_class", homework, report, examPrep = "exam_prep"

    var label: String {
        switch self {
        case .inClass: "수업 중 과제"
        case .homework: "숙제"
        case .report: "레포트"
        case .examPrep: "시험 준비"
        }
    }

    var symbol: String {
        switch self {
        case .inClass: "timer"
        case .homework: "house"
        case .report: "doc.richtext"
        case .examPrep: "graduationcap"
        }
    }
}

struct LectureTask: Codable, Identifiable, Hashable {
    let id: Int
    let sessionId: String
    let pageNo: Int?
    let kind: TaskKind
    let title: String
    let instructions: String
    let dueText: String
    var done: Bool
    var draft: TaskDraft?
}

/// AI가 강의 내용을 근거로 만든 과제 초안
struct TaskDraft: Codable, Hashable {
    let checklist: [String]
    let outline: [String]
    let draft: String
    let sources: [Int]
}

/// AI를 기다리지 않고 서버가 규칙으로 바로 띄우는 임시 필기
struct AnnotationPreview: Decodable, Hashable {
    let id: String
    let pageNo: Int
    let blockId: Int?
    let type: AnnotationType
    let text: String
    let startMs: Int
}

/// 자막 모드: 교수님이 지금 설명하는 페이지와 문단
struct SpokenSpot: Hashable {
    let pageNo: Int
    let blockId: Int?
}

/// 자막 모드의 큰 알림 (시험 언급·공지)
struct ImportantAlert: Identifiable, Hashable {
    let id = UUID()
    let symbol: String
    let title: String
    let text: String
}

/// 딴생각 따라잡기 (POST /sessions/{id}/catch-up)
struct CatchUp: Codable, Hashable {
    let points: [String]
    let pages: [Int]
    let fromMs: Int
    let toMs: Int
}

/// 교수님만 말한 내용 (GET /sessions/{id}/beyond-slides)
struct BeyondSlides: Codable, Hashable {
    let ratio: Double
    let annotationIds: [Int]
}

// 공부 도구 (GET /sessions/{id}/study/{kind})

struct StudyResponse<Payload: Decodable>: Decodable {
    let status: String
    let done: Int?
    let total: Int?
    let body: Payload?
    let stale: Bool?
}

struct Flashcard: Codable, Hashable {
    let front: String
    let back: String
    let pageNo: Int?
}

struct Concept: Codable, Hashable {
    let term: String
    let definition: String
    let example: String?
    let pageNo: Int?
}

struct MindNode: Codable, Hashable, Identifiable {
    let label: String
    let pageNo: Int?
    let children: [MindNode]?
    var id: String { "\(pageNo ?? 0)-\(label)" }
}

struct ClozeItem: Codable, Hashable {
    let pageNo: Int
    let text: String
    let answer: String
    let important: Bool
}

struct TutorReply: Codable, Hashable {
    let answer: String
    let pages: [Int]
}

struct TutorMessage: Codable, Hashable, Identifiable {
    var id = UUID()
    let role: String
    let content: String
    var pages: [Int] = []
}

/// 실시간 용어 사전: 강의 중에 처음 나온 전문용어
struct GlossaryTerm: Codable, Hashable, Identifiable {
    let id: Int
    let pageNo: Int?
    let term: String
    let definition: String
    let startMs: Int
}
