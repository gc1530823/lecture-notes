from app.text_fix import fix_terms, note_type, vocabulary

SLIDES = ["과적합 방지: L2 정규화, 드롭아웃, 조기 종료",
          "드롭아웃은 뉴런 일부를 끈다. 검증 손실이 오르면 멈춘다",
          "손실 함수의 기울기 반대 방향으로 이동"]


def test_misheard_terms_are_fixed_from_slide_vocabulary():
    vocab = vocabulary(SLIDES)
    assert fix_terms("학습할 때 유런 일부를 꺼버려요", vocab) == "학습할 때 뉴런 일부를 꺼버려요"
    assert fix_terms("범증 손실이 다시 올라가면", vocab) == "검증 손실이 다시 올라가면"
    assert fix_terms("유런을 끈다", vocab) == "뉴런을 끈다"


def test_ordinary_words_are_left_alone():
    vocab = vocabulary(SLIDES)
    for text in ["모르면 질문하세요", "기울지 않게", "다음 장 역전파 입니다", "학습률이 클 때와 작을 때"]:
        assert fix_terms(text, vocab) == text


def test_exam_mentions_become_exam_notes():
    assert note_type("emphasis", "학습률 차이는 중간고사에 꼭 나오는 핵심 내용") == "exam"
    assert note_type("example", "시험 문제를 외워서 푸는 학생과 비슷") == "example"
    assert note_type("notice", "기말고사 범위는 7장까지") == "notice"
