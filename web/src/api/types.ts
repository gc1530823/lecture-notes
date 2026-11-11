// 서버 응답 모양. 서버 엔드포인트가 응답 모델을 선언하지 않아 OpenAPI 타입이 비어 있으므로 db.py·main.py를 보고 적었다.

export type NoteType = "explanation" | "example" | "emphasis" | "exam" | "notice" | "tip" | "qa";

export interface SessionBrief {
  id: string;
  status: "recording" | "processing" | "done" | string;
  started_at: number;
}

export interface DocumentBrief {
  id: string;
  title: string;
  page_count: number;
  created_at: number;
  kind: "slides" | "notebook" | "meeting" | string;
  course?: string; // 과목 (폴더). 비면 "과목 없음"
  sessions: SessionBrief[];
}

export interface Block { id: number; x: number; y: number; w: number; h: number; text: string }
export interface Page { id: number; page_no: number; width: number; height: number; blocks: Block[]; text?: string }
export interface DocumentDetail extends Omit<DocumentBrief, "sessions"> { keywords: string[]; pages: Page[] }

export interface Annotation {
  id: number;
  page_no: number;
  block_id: number | null;
  type: NoteType;
  text: string;
  start_ms: number;
  pending: boolean;
  edited_by_user: boolean;
  photo_id?: number | null; // 칠판 사진으로 만든 필기
  confidence?: number; // AI가 그 쪽이 맞다고 본 확신 (0~1). 낮으면 "확인 필요"
}

export interface Segment { start_ms: number; end_ms: number; text: string; page_no: number | null }

export interface GlossaryTerm { id: number; page_no: number | null; term: string; definition: string; start_ms: number }

export interface SummaryBody {
  overview: string;
  pages: { page_no: number; summary: string }[];
  quiz?: { page_no: number; question: string; choices: string[]; answer_index: number; explanation: string }[];
}
export interface SummaryResponse { status: string; summary: SummaryBody | null; progress: unknown }

export interface StudyResponse<T> { status: "ready" | "building" | "none" | string; done?: number; total?: number; body: T | null; stale?: boolean }
export interface Flashcard { front: string; back: string; page_no: number }
export interface Concept { term: string; definition: string; example: string; page_no: number }
export interface MindNode { label: string; page_no?: number | null; children?: MindNode[] }
export interface ClozeItem { page_no: number; text: string; answer: string; important: boolean }

export interface ExamPage { page_no: number; score: number; level: "high" | "medium" | "low"; reasons: string[] }
export interface ExamMap { lectures: number; pages: ExamPage[]; top: number[]; questions: unknown[]; job: { status: string } }

export interface TutorReply { answer: string; pages: number[] }
