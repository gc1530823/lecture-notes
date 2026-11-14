from datetime import date, datetime

from app.due import KST, parse_due

# 2026-11-11 수요일 (한국 시각) 에 받은 과제
BASE = datetime(2026, 11, 11, 10, 0, tzinfo=KST).timestamp()


def test_weekday_phrases():
    assert parse_due("다음 주 금요일까지 LMS 제출", BASE) == date(2026, 11, 20)
    assert parse_due("이번 주 금요일", BASE) == date(2026, 11, 13)
    assert parse_due("금요일까지", BASE) == date(2026, 11, 13)
    assert parse_due("수요일까지", BASE) == date(2026, 11, 18)


def test_dates_and_relative():
    assert parse_due("11월 20일까지", BASE) == date(2026, 11, 20)
    assert parse_due("1월 10일", BASE) == date(2027, 1, 10)
    assert parse_due("12/3 자정", BASE) == date(2026, 12, 3)
    assert parse_due("내일까지", BASE) == date(2026, 11, 12)
    assert parse_due("2주 뒤", BASE) == date(2026, 11, 25)


def test_unknown():
    assert parse_due("", BASE) is None
    assert parse_due("다음 수업 전까지", BASE) is None
