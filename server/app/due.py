"""과제 마감 글('다음 주 금요일까지', '11월 20일', '내일')을 날짜로 (할 일 달력).

강의를 녹음한 날을 기준으로 센다. 알 수 없으면 None (달력의 '날짜 모름'에 둔다).
"""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
_DAYS = "월화수목금토일"


def parse_due(text: str, base_ts: float) -> date | None:
    if not text:
        return None
    t = re.sub(r"\s+", "", text)
    base = datetime.fromtimestamp(base_ts, KST).date()

    m = re.search(r"(?:(\d{4})년)?(\d{1,2})월(\d{1,2})일", t) or re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", t)
    if m:
        groups = m.groups()
        year, month, day = (int(groups[0]) if groups[0] else None, int(groups[1]), int(groups[2])) if len(groups) == 3 \
            else (None, int(groups[0]), int(groups[1]))
        try:
            when = date(year or base.year, month, day)
        except ValueError:
            return None
        if year is None and when < base - timedelta(days=60):  # 12월에 받은 '1월 10일'은 다음 해
            when = date(base.year + 1, month, day)
        return when

    for word, n in (("모레", 2), ("내일", 1), ("오늘", 0)):
        if word in t:
            return base + timedelta(days=n)
    m = re.search(r"(\d{1,2})(주|일)(?:후|뒤)", t)
    if m:
        return base + timedelta(days=int(m.group(1)) * (7 if m.group(2) == "주" else 1))

    m = re.search(r"(다음|담|다다음|이번)?주?([월화수목금토일])요일", t)
    if m:
        target = _DAYS.index(m.group(2))
        monday = base - timedelta(days=base.weekday())
        if m.group(1) in ("다음", "담"):
            return monday + timedelta(days=7 + target)
        if m.group(1) == "다다음":
            return monday + timedelta(days=14 + target)
        when = monday + timedelta(days=target)
        if m.group(1) is None and when <= base:  # 그냥 '금요일까지' = 다가오는 금요일
            when += timedelta(days=7)
        return when
    if re.search(r"다음주|담주", t):
        return base - timedelta(days=base.weekday()) + timedelta(days=11)  # 날을 안 말하면 다음 주 금요일로
    return None
