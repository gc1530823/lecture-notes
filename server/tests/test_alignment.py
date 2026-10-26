from app.alignment import PageIndex, PageTracker

PAGES = [
    "경사하강법 (Gradient Descent)\n손실 함수의 기울기 반대 방향으로 이동\n학습률이 이동 크기를 정한다",
    "역전파 (Backpropagation)\n연쇄 법칙으로 기울기를 계산\n출력층에서 입력층 방향으로 오차 전달",
    "과적합과 정규화\n학습 데이터에만 지나치게 맞춰지는 현상\nL2 정규화, 드롭아웃, 조기 종료",
    "합성곱 신경망 (CNN)\n필터로 이미지의 특징을 추출\n풀링으로 크기를 줄인다",
]


def tracker() -> PageTracker:
    return PageTracker(PageIndex(PAGES))


def test_similarity_picks_matching_page():
    sims = PageIndex(PAGES).similarities("드롭아웃이랑 조기 종료로 과적합을 막아요")
    assert max(range(len(sims)), key=sims.__getitem__) == 2


def test_progresses_forward_with_speech():
    t = tracker()
    est = t.observe("경사하강법은 기울기 반대 방향으로 이동하는 거예요", 0)
    assert est.page_no == 1
    for i, text in enumerate(["역전파는 연쇄 법칙으로 기울기를 계산합니다",
                              "출력층에서 입력층 방향으로 오차를 전달해요",
                              "역전파에서 연쇄 법칙이 핵심이에요"]):
        est = t.observe(text, 40_000 + i * 5_000)
    assert est.page_no == 2
    assert est.confidence > 0.6


def test_one_off_word_does_not_make_page_jump():
    t = tracker()
    for i in range(3):
        t.observe("경사하강법에서 학습률이 이동 크기를 정해요", i * 5_000)
    # 지나가듯 다른 페이지 단어 하나가 나와도 바로 튀지 않는다
    est = t.observe("나중에 CNN에서도 쓰여요", 16_000)
    assert est.page_no == 1


def test_explicit_page_number_and_next_phrase():
    t = tracker()
    t.observe("시작할게요", 0)
    assert t.observe("자 이제 3페이지 볼게요", 5_000).page_no == 3
    est = t.observe("다음 장으로 넘어갈게요", 10_000)
    assert est.page_no == 4


def test_recent_user_page_is_trusted_most():
    t = tracker()
    t.user_viewed(3, now=100.0)
    est = t.observe("음 그러니까요", 0, now=105.0)
    assert est.page_no == 3


def test_vague_speech_is_low_confidence_with_candidates():
    t = tracker()
    t.user_viewed(2, now=0.0)
    t.observe("역전파는 연쇄 법칙", 0, now=1.0)
    est = t.observe("기울기 방향", 60_000, now=200.0)
    # 여러 페이지에 걸치는 애매한 말에는 페이지를 바꾸지 않고, 후보 3개를 함께 낸다
    assert est.page_no == 2
    assert len(est.candidates) == 3
