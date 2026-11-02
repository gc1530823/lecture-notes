from app.exam_map import score_pages, top_pages


def seg(page, text, start=0, end=60000):
    return {"page_no": page, "text": text, "start_ms": start, "end_ms": end}


def note(page, type_):
    return {"page_no": page, "type": type_, "pending": False}


def test_exam_talk_and_emphasis_rank_pages_with_reasons():
    sessions = [
        {"segments": [seg(1, "경사하강법은 기울기 반대로 가요."), seg(2, "이거 중간고사에 꼭 나와요."),
                      seg(3, "과적합은 외운 학생 같아요.", 0, 240000)],
         "annotations": [note(2, "exam"), note(3, "emphasis"), note(3, "qa")]},
        {"segments": [seg(3, "과적합 다시 볼게요.")], "annotations": []},
    ]
    scores = {s["page_no"]: s for s in score_pages([1, 2, 3, 4], sessions)}
    assert scores[2]["score"] == 1.0 and scores[2]["level"] == "high"
    assert "교수님이 시험에 나온다고 함 1번" in scores[2]["reasons"] and "시험 필기 1개" in scores[2]["reasons"]
    assert "강의 2번에서 다룸" in scores[3]["reasons"] and "수업 중 질문 1개" in scores[3]["reasons"]
    assert scores[4] == {"page_no": 4, "score": 0.0, "level": "low", "reasons": []}
    assert top_pages(list(scores.values()))[:2] == [2, 3]


def test_no_lectures_means_no_predictions():
    scores = score_pages([1, 2], [])
    assert all(s["level"] == "low" for s in scores) and top_pages(scores) == []
