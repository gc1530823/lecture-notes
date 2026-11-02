from app.beyond import beyond_slides, coverage

SLIDE = "경사하강법 (Gradient Descent) 손실 함수의 기울기 반대 방향으로 이동 학습률 η가 이동 크기를 정한다"


def test_coverage_separates_slide_reading_from_extra_explanation():
    assert coverage("손실 함수의 기울기 반대 방향으로 이동해요", SLIDE) > 0.9
    assert coverage("산에서 눈 감고 가장 가파른 쪽으로 한 걸음씩 내려가는 것과 같음", SLIDE) < 0.1


def test_beyond_slides_ratio_and_notes():
    segments = [{"page_no": 1, "text": "손실 함수의 기울기 반대 방향으로 이동해요"},
                {"page_no": 1, "text": "산에서 눈 감고 내려가는 것과 같아요"}]
    notes = [{"id": 1, "page_no": 1, "type": "example", "text": "산에서 눈 감고 내려가는 것과 같음", "pending": False},
             {"id": 2, "page_no": 1, "type": "explanation", "text": "손실 함수의 기울기 반대 방향으로 이동", "pending": False},
             {"id": 3, "page_no": 1, "type": "notice", "text": "과제는 금요일까지", "pending": False}]
    result = beyond_slides({1: SLIDE}, segments, notes)
    assert 0.4 < result["ratio"] < 0.6 and result["annotation_ids"] == [1]
