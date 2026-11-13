from app import quiz


def test_clean_set_drops_recording_questions_and_bad_choices():
    items = [
        {"type": "mcq", "page_no": 3, "question": "교착 상태의 필요조건이 아닌 것은?", "choices": ["상호 배제", "점유 대기", "비선점", "선점"], "answer_index": 3},
        {"type": "short", "page_no": 3, "question": "교수님이 12분에 말한 예시는?", "answer": "식사하는 철학자"},
        {"type": "mcq", "page_no": 3, "question": "보기가 셋뿐인 문제입니다", "choices": ["a", "b", "c"], "answer_index": 0},
        {"type": "ox", "page_no": 99, "question": "세마포는 정수 변수다.", "answer": "o"},
    ]
    out = quiz.clean_set(items, {1, 2, 3})
    assert [q["type"] for q in out] == ["mcq", "ox"]
    assert out[0]["answer"] == "선점"
    assert out[1]["answer"] == "O" and out[1]["page_no"] == 1


def test_quick_grade():
    mcq = {"type": "mcq", "choices": ["a", "b", "c", "d"], "answer_index": 2, "answer": "c"}
    assert quiz.quick_grade(mcq, "C")["verdict"] == "correct"
    assert quiz.quick_grade(mcq, "1")["verdict"] == "wrong"
    assert quiz.quick_grade({"type": "ox", "answer": "X"}, "틀림")["verdict"] == "correct"
    fill = {"type": "fill", "answer": "1, 0", "accept": []}
    assert quiz.quick_grade(fill, "1 0")["verdict"] == "correct"
    assert quiz.quick_grade({"type": "short", "answer": "Mutex", "accept": ["뮤텍스"]}, "뮤 텍스")["verdict"] == "correct"
    assert quiz.quick_grade({"type": "essay", "answer": "긴 답", "accept": []}, "다른 답") is None
    assert quiz.quick_grade({"type": "essay", "answer": "x"}, " ")["verdict"] == "wrong"


def test_material_uses_slides_speech_and_exam_notes():
    pages = [{"page_no": 1, "text": "세마포 개념"}, {"page_no": 2, "text": ""}]
    sessions = [{"segments": [{"page_no": 1, "text": "초기값은 1로 둡니다"}],
                 "annotations": [{"page_no": 1, "type": "exam", "text": "초기값 시험에 나옴"}], "summaries": {}}]
    text = quiz.material(pages, sessions)
    assert "세마포 개념" in text and "초기값은 1로" in text and "시험에 나온다고" in text
    assert 'no="2"' not in text
