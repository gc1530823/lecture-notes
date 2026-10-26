"""자동 슬라이드 정렬: 교수님이 지금 설명하는 페이지를 추정한다.

세 신호를 HMM 전방(forward) 알고리즘으로 합친다.
- 신호 A: 사용자가 보고 있는 페이지. 직접 넘긴 직후에는 가장 크게 믿는다.
- 신호 B: 최근 30초 받아쓰기와 각 페이지 텍스트의 유사도 (글자 2-gram TF-IDF 코사인).
- 신호 C: "다음 장", "앞에서 본 것처럼", "5페이지" 같은 전환 발언.
전이 확률에는 "강의는 대체로 앞으로 진행된다"는 가정을 넣어 추정 페이지가 튀지 않게 한다.

외부 임베딩 API 없이 동작한다. 한국어는 띄어쓰기·조사 변화가 많아 단어보다 글자 2-gram이 안정적이다.
"""

import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field

WINDOW_MS = 30_000
USER_TRUST_SECONDS = 20.0
SIM_FLOOR = 0.05
CURRENT_WEIGHT = 0.6
SIM_TEMPERATURE = 0.1

# 전이 확률 (현재 페이지 기준)
P_STAY = 0.80
P_NEXT = 0.12
P_SKIP = 0.03   # 한 장 건너뛰기
P_BACK = 0.03
P_JUMP = 0.02   # 나머지 아무 페이지로

NEXT_PATTERNS = re.compile(r"다음\s*(장|페이지|슬라이드|쪽|거|으로)|넘어가|넘길게|넘겨|그 다음 장")
BACK_PATTERNS = re.compile(r"앞에서|아까\s*(본|봤|말한|했)|이전\s*(장|페이지|슬라이드)|다시 앞|돌아가")
# 주제가 바뀌는 말: 이전 받아쓰기를 유사도 계산에서 빼기만 한다 (다음 장으로 넘어간다고 단정하지 않음)
TOPIC_SHIFT = re.compile(r"자\s*이제|이번에는|이제\s*.{0,12}(이야기|얘기|볼게|봅시다|넘어)")
PAGE_NUMBER = re.compile(r"(\d{1,3})\s*(페이지|쪽|번\s*슬라이드|슬라이드)")


# 말끝·조사는 어느 페이지에나 나와서 유사도에 잡음만 준다
ENDINGS = ("습니다", "입니다", "합니다", "할게요", "갈게요", "볼게요", "에서는", "으로는", "거예요", "이에요", "예요",
           "해요", "어요", "아요", "에요", "게요", "니다", "으로", "에서", "에게", "까지", "부터", "하는", "하고",
           "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "요")
FILLERS = {"그래서", "그러니까", "이제", "그리고", "근데", "그런데", "이거", "저거", "여기", "거기", "우리", "여러분",
           "이렇게", "그렇게", "약간", "진짜", "그냥", "이런", "그런", "있어요", "없어요", "합니다", "해요"}


def _stem(word: str) -> str:
    for ending in ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 2:
            return word[: -len(ending)]
    return word


def _grams(text: str) -> Counter[str]:
    text = re.sub(r"\s+", " ", text.lower())
    grams: Counter[str] = Counter()
    for word in re.findall(r"[a-z0-9]+|[가-힣]+", text):
        if re.match(r"[a-z0-9]", word):
            if len(word) >= 2:
                grams[word] += 1
        elif word not in FILLERS:
            word = _stem(word)
            grams.update(word[i:i + 2] for i in range(len(word) - 1))
    return grams


class PageIndex:
    """페이지 텍스트를 TF-IDF 벡터로 만들어 두고 받아쓰기와 유사도를 잰다."""

    def __init__(self, page_texts: list[str]):
        self.size = len(page_texts)
        counts = [_grams(t) for t in page_texts]
        df: Counter[str] = Counter()
        for c in counts:
            df.update(c.keys())
        self.idf = {g: math.log((1 + self.size) / (1 + n)) + 1 for g, n in df.items()}
        self.vectors = [self._weigh(c) for c in counts]

    def _weigh(self, counts: Counter[str]) -> dict[str, float]:
        vec = {g: (1 + math.log(n)) * self.idf.get(g, 0.0) for g, n in counts.items() if g in self.idf}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {g: v / norm for g, v in vec.items()}

    def similarities(self, text: str) -> list[float]:
        query = self._weigh(_grams(text))
        return [sum(w * page.get(g, 0.0) for g, w in query.items()) for page in self.vectors]


@dataclass
class Estimate:
    page_no: int
    confidence: float
    candidates: list[int]   # 확률 높은 순 페이지 (최대 3개)


@dataclass
class PageTracker:
    index: PageIndex
    belief: list[float] = field(default_factory=list)
    window: list[tuple[int, str]] = field(default_factory=list)
    user_page: int | None = None
    user_page_at: float = -1e9

    def __post_init__(self) -> None:
        n = self.index.size
        # 강의는 보통 앞쪽에서 시작한다
        self.belief = [1.0 / n] * n if n else []
        if n:
            self.belief = _normalize([2.0 if i == 0 else 1.0 for i in range(n)])

    # 신호 A
    def user_viewed(self, page_no: int, now: float | None = None, manual: bool = True) -> None:
        """manual=False는 강의 시작 때 펴 둔 페이지처럼 직접 넘긴 게 아닌 경우: 약하게만 믿는다."""
        if 1 <= page_no <= self.index.size:
            self.user_page = page_no
            self.user_page_at = (time.monotonic() if now is None else now) if manual else -1e9

    def observe(self, text: str, start_ms: int, now: float | None = None) -> Estimate:
        """받아쓰기 한 문장을 반영하고 현재 페이지 추정을 돌려준다."""
        n = self.index.size
        now = time.monotonic() if now is None else now
        # 전환 발언이 나오면 이전 페이지 이야기는 유사도 계산에서 뺀다
        if any(p.search(text) for p in (NEXT_PATTERNS, BACK_PATTERNS, PAGE_NUMBER, TOPIC_SHIFT)):
            self.window = []
        self.window.append((start_ms, text))
        self.window = [(t, s) for t, s in self.window if t >= start_ms - WINDOW_MS]

        prior = self._transition(text)

        # 신호 B: 유사도가 높을수록 그 페이지일 가능성이 크다.
        # 겹치는 글자가 조금뿐인 약한 유사도(0.05 이하)는 무시해서 우연한 겹침에 흔들리지 않게 한다.
        # 방금 들어온 문장(60%)과 최근 30초 전체(40%)를 섞는다: 주제가 바뀌면 빨리 따라가고, 한 문장의 우연한 겹침에는 덜 흔들린다
        current = self.index.similarities(text)
        recent = self.index.similarities(" ".join(s for _, s in self.window))
        sims = [CURRENT_WEIGHT * c + (1 - CURRENT_WEIGHT) * r for c, r in zip(current, recent)]
        emission = [math.exp(max(s - SIM_FLOOR, 0.0) / SIM_TEMPERATURE) for s in sims]

        # 신호 A: 방금 직접 넘긴 페이지는 강하게, 시간이 지나면 약하게
        user = [1.0] * n
        if self.user_page:
            recent = now - self.user_page_at < USER_TRUST_SECONDS
            weight = 6.0 if recent else 1.6
            user[self.user_page - 1] = weight

        self.belief = _normalize([p * e * u for p, e, u in zip(prior, emission, user)])
        order = sorted(range(n), key=lambda i: self.belief[i], reverse=True)
        return Estimate(page_no=order[0] + 1, confidence=self.belief[order[0]], candidates=[i + 1 for i in order[:3]])

    def _transition(self, text: str) -> list[float]:
        n = self.index.size
        stay, nxt, skip, back = P_STAY, P_NEXT, P_SKIP, P_BACK
        # 신호 C: 전환 발언이 있으면 전이 확률을 바꾼다
        if NEXT_PATTERNS.search(text):
            stay, nxt = 0.30, 0.60
        if BACK_PATTERNS.search(text):
            stay, back = 0.55, 0.35
        prior = [0.0] * n
        for j, p in enumerate(self.belief):
            row = [P_JUMP / max(n - 1, 1)] * n
            row[j] = stay
            if j + 1 < n:
                row[j + 1] = nxt
            if j + 2 < n:
                row[j + 2] = skip
            if j - 1 >= 0:
                row[j - 1] = back
            row = _normalize(row)
            for i in range(n):
                prior[i] += p * row[i]
        number = PAGE_NUMBER.search(text)
        if number and 1 <= int(number.group(1)) <= n:
            prior[int(number.group(1)) - 1] += 0.6
        return _normalize(prior)


def _normalize(values: list[float]) -> list[float]:
    total = sum(values)
    return [v / total for v in values] if total > 0 else values
