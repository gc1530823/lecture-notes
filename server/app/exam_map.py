"""시험 예상 지도: 그 강의자료로 들은 모든 강의를 모아 페이지마다 "시험에 나올 만한 정도"를 점수로 매긴다.

AI 없이 규칙으로 바로 계산하고, 점수마다 이유를 붙여 학생이 왜 중요한지 알 수 있게 한다.
- 교수님이 시험에 나온다고 한 말 (받아쓰기에서 직접 찾음, 가장 크게 본다)
- 시험·강조 필기, 학생이 수업 중에 물어본 질문
- 그 페이지를 설명한 시간 (오래 설명할수록 중요하다고 본다)
- 여러 강의에서 다시 다룬 페이지
"""

from .quick_notes import EXAM_TALK

WEIGHTS = {"exam_talk": 5.0, "exam": 4.0, "emphasis": 2.0, "qa": 1.0, "minute": 1.0, "revisit": 1.5}
# 이 점수 이상이면 '높음', 절반 이상이면 '보통' (점수는 가장 높은 페이지를 1로 맞춘다)
HIGH, MEDIUM = 0.6, 0.3


def _speech_minutes(segments: list[dict]) -> float:
    return sum(max(s["end_ms"] - s["start_ms"], 0) for s in segments) / 60000


def score_pages(page_nos: list[int], sessions: list[dict]) -> list[dict]:
    """sessions: [{"segments": [...], "annotations": [...]}]. 페이지마다 {page_no, score, level, reasons}."""
    raw = {}
    for no in page_nos:
        exam_talk = exam = emphasis = qa = lectures = 0
        minutes = 0.0
        for session in sessions:
            segments = [s for s in session["segments"] if s["page_no"] == no]
            notes = [a for a in session["annotations"] if a["page_no"] == no and not a["pending"]]
            if segments:
                lectures += 1
            minutes += _speech_minutes(segments)
            exam_talk += sum(1 for s in segments if EXAM_TALK.search(s["text"]))
            exam += sum(1 for a in notes if a["type"] == "exam")
            emphasis += sum(1 for a in notes if a["type"] == "emphasis")
            qa += sum(1 for a in notes if a["type"] == "qa")
        points = (WEIGHTS["exam_talk"] * exam_talk + WEIGHTS["exam"] * exam + WEIGHTS["emphasis"] * emphasis
                  + WEIGHTS["qa"] * qa + WEIGHTS["minute"] * min(minutes, 10)
                  + WEIGHTS["revisit"] * max(lectures - 1, 0))
        reasons = []
        if exam_talk:
            reasons.append(f"교수님이 시험에 나온다고 함 {exam_talk}번")
        if exam:
            reasons.append(f"시험 필기 {exam}개")
        if emphasis:
            reasons.append(f"강조 {emphasis}번")
        if qa:
            reasons.append(f"수업 중 질문 {qa}개")
        if minutes >= 0.5:
            reasons.append(f"설명 {minutes:.0f}분" if minutes >= 1 else "설명 1분 미만")
        if lectures > 1:
            reasons.append(f"강의 {lectures}번에서 다룸")
        raw[no] = (points, reasons)

    top = max((p for p, _ in raw.values()), default=0) or 1
    result = []
    for no in page_nos:
        points, reasons = raw[no]
        score = round(points / top, 3)
        level = "high" if score >= HIGH and points else "medium" if score >= MEDIUM and points else "low"
        result.append({"page_no": no, "score": score, "level": level, "reasons": reasons})
    return result


def top_pages(scores: list[dict], limit: int = 3) -> list[int]:
    ranked = sorted((s for s in scores if s["level"] != "low"), key=lambda s: -s["score"])
    return [s["page_no"] for s in ranked[:limit]]
