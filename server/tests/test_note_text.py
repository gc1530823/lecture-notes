"""AI 필기는 학생 노트처럼 내용만: '시험에 꼭 나온다'·'꼭 기억하세요' 같은 말은 꼬리표가 보여 주므로 뺀다"""
from app.note_text import tidy


def test_tidy_keeps_content_and_drops_meta_phrases():
    assert tidy("교착 상태 네 조건(상호 배제·점유와 대기·비선점·순환 대기)은 시험에 꼭 나온다") == \
        "교착 상태 네 조건(상호 배제·점유와 대기·비선점·순환 대기)"
    assert tidy("교착 상태(Deadlock)는 중간고사 범위에 포함됩니다. 꼭 기억하세요.") == "교착 상태(Deadlock): 중간고사 범위"
    assert tidy("학습률이 너무 크면 발산. 이거 시험에 나옴") == "학습률이 너무 크면 발산"
    assert tidy("은행원 알고리즘 — 중요!") == "은행원 알고리즘"
    assert tidy("안전 상태 유지 시에만 자원 할당 (교수님 강조함)") == "안전 상태 유지 시에만 자원 할당"


def test_tidy_drops_notes_with_no_content_and_leaves_real_content_alone():
    assert tidy("이거 시험에 꼭 나와요.") == ""
    assert tidy("시험 문제 유형: 서술형 2문제, 객관식 10문제") == "시험 문제 유형: 서술형 2문제, 객관식 10문제"
    assert tidy("회귀는 평균제곱오차, 분류는 교차 엔트로피") == "회귀는 평균제곱오차, 분류는 교차 엔트로피"
