from app.quick_notes import quick_note

BLOCKS = [
    {"id": 1, "text": "경사하강법 (Gradient Descent)"},
    {"id": 2, "text": "학습률 η가 이동 크기를 정한다"},
]


def test_exam_sentence_wins_and_sits_by_matching_block():
    note = quick_note(BLOCKS, ["산에서 내려가는 거예요.", "학습률이 클 때와 작을 때 차이는 중간고사에 꼭 나와요."])
    assert note["type"] == "exam"
    assert note["block_id"] == 2
    assert note["text"].startswith("학습률이 클 때와")


def test_plain_explanation_picks_sentence_that_matches_slide():
    note = quick_note(BLOCKS, ["음 그러니까요.", "자 경사하강법은 기울기 반대 방향으로 가는 거예요."])
    assert note["type"] == "explanation"
    assert note["block_id"] == 1
    assert note["text"].startswith("경사하강법은")   # 말머리 "자"는 뗀다


def test_long_sentence_is_shortened():
    note = quick_note([], ["이건 아주 긴 문장인데 " * 10])
    assert len(note["text"]) <= 71 and note["text"].endswith("…")
    assert note["block_id"] is None


def test_exam_analogy_is_not_exam_notice():
    note = quick_note(BLOCKS, ["시험 문제를 외워서 푸는 학생이랑 비슷해요."])
    assert note["type"] == "example"
    assert quick_note(BLOCKS, ["이건 시험에 꼭 나와요."])["type"] == "exam"


def test_whisper_chunks_are_split_into_sentences_with_times():
    from app.stt import Segment, split_sentences

    out = split_sentences([Segment(0, 10000, "이거 중간고사에 꼭 나와요. 다음 장, 역전파입니다.")])
    assert [s.text for s in out] == ["이거 중간고사에 꼭 나와요.", "다음 장, 역전파입니다."]
    assert out[0].start_ms == 0 and out[0].end_ms == out[1].start_ms and out[1].end_ms == 10000
