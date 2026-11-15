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


def test_next_phrase_moves_on_despite_page_opened_at_start():
    t = tracker()
    t.user_viewed(1, now=0.0, manual=False)
    t.observe("경사하강법은 기울기 반대 방향으로 이동해요", 0, now=1.0)
    t.observe("학습률이 이동 크기를 정해요", 5_000, now=6.0)
    est = t.observe("다음 장, 역전파입니다. 연쇄 법칙을 반복해서 써요", 10_000, now=11.0)
    assert est.page_no == 2


def test_full_lecture_scenario_tracks_every_sentence():
    # 시뮬레이터의 강의 시나리오: "다음 장" 없이 "자 이제 과적합 이야기"로 넘어가는 부분도 따라가야 한다
    from scripts.simulate_lecture import SLIDES, SPEECH

    t = PageTracker(PageIndex(["\n".join(lines) for lines in SLIDES]))
    t.user_viewed(1, now=0.0, manual=False)
    got = [t.observe(text, i * 1500, now=1.0 + i).page_no for i, (_, text) in enumerate(SPEECH)]
    assert got == [page for page, _ in SPEECH]


def test_english_terms_spoken_in_korean_match_english_slides():
    """슬라이드는 영어, 말은 한국어: "그래디언트 디센트"를 "Gradient Descent" 쪽으로 따라간다."""
    from app.alignment import PageIndex, PageTracker, hangul_skeleton, latin_skeleton

    assert hangul_skeleton("백프로파게이션") == latin_skeleton("backpropagation")
    assert hangul_skeleton("드롭아웃") == latin_skeleton("dropout")
    index = PageIndex(["Gradient Descent\nlearning rate controls step size", "Backpropagation\nchain rule",
                       "Overfitting and Regularization\ndropout"])
    for text, page in [("그래디언트 디센트에서는 스텝 크기가 중요해요", 0), ("백프로파게이션은 미분을 뒤로 전달합니다", 1),
                       ("오버피팅을 막으려면 드롭아웃을 써요", 2)]:
        sims = index.similarities(text)
        assert sims.index(max(sims)) == page and max(sims) > 0.3
    # 보통 한국어 문장은 영어 낱말로 잘못 바뀌지 않는다
    for text in ["그러니까 여러분 이거는 정말 중요합니다", "다음 시간에는 중간고사 범위를 알려 드릴게요", "자 그러면 질문 있는 사람 손 들어 보세요"]:
        assert not index._spoken_english(text), text
    tracker = PageTracker(index)
    tracker.observe("그래디언트 디센트부터 볼게요", 0, now=0)
    assert tracker.observe("자 이제 백프로파게이션은 체인 룰을 씁니다", 20_000, now=20).page_no == 2


def test_pinned_page_wins_until_unpinned():
    """'이 쪽 고정': 교수님이 다른 쪽 얘기를 해도 고정한 쪽에 붙고, 풀면 그 쪽에서부터 다시 따라간다"""
    t = tracker()
    t.pin(1)
    est = t.observe("합성곱 신경망은 필터로 이미지의 특징을 추출하고 풀링으로 크기를 줄여요", 0)
    assert est.page_no == 1 and est.confidence == 1.0
    t.pin(None)
    for i in range(3):
        est = t.observe("합성곱 신경망은 필터로 이미지의 특징을 추출하고 풀링으로 크기를 줄여요", 10_000 + i * 5_000)
    assert est.page_no == 4
    t.pin(9)   # 없는 쪽은 무시
    assert t.pinned is None


def test_underscore_names_match_joined_or_spoken_korean():
    """슬라이드의 FIND_IN_SET 을 받아쓰기의 'findinset'·'파인드 인셋'과 같은 말로 본다 (실제 DB 강의에서 찾은 문제)"""
    idx = PageIndex(["INSTR(str, substr) : 부분 문자열 위치", "FIND_IN_SET(str, strlist) : 목록에서 위치 찾기", "REPLACE(str, from, to)"])
    for spoken in ("findinset 이라는 함수는", "파인드 인셋을 어디에 써야 되느냐가 중요한데"):
        sims = idx.similarities(spoken)
        assert max(range(3), key=sims.__getitem__) == 1, (spoken, sims)
