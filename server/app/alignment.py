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

# 한국어와 영어 강의 둘 다 (공개 강의 테스트가 영어라서)
NEXT_PATTERNS = re.compile(r"다음\s*(장|페이지|슬라이드|쪽|거|으로)|넘어가|넘길게|넘겨|그 다음 장"
                           r"|\bnext (slide|page)\b|\bmove on\b|\bgo on to\b|\bon to the next\b", re.I)
BACK_PATTERNS = re.compile(r"앞에서|아까\s*(본|봤|말한|했)|이전\s*(장|페이지|슬라이드)|다시 앞|돌아가"
                           r"|\b(go|going|went) back\b|\bprevious (slide|page)\b|\bearlier (we|i)\b|\bas we saw\b", re.I)
# 주제가 바뀌는 말: 이전 받아쓰기를 유사도 계산에서 빼기만 한다 (다음 장으로 넘어간다고 단정하지 않음)
TOPIC_SHIFT = re.compile(r"자\s*이제|이번에는|이제\s*.{0,12}(이야기|얘기|볼게|봅시다|넘어)"
                         r"|\b(now )?let'?s (talk|look|move|turn)\b|\bso now\b|\bnext,? (we|i)\b", re.I)
PAGE_NUMBER = re.compile(r"(\d{1,3})\s*(페이지|쪽|번\s*슬라이드|슬라이드)|\b(?:slide|page)\s+(\d{1,3})\b", re.I)
# 강의는 앞에서 시작한다: 처음 믿음은 앞쪽 몇 장에 몰아 둔다 (예전에는 고르게 두어서, 첫 문장이 우연히 겹친
# 맨 뒤 '요약'·저작권 쪽으로 튀고 한참 못 돌아왔다)
START_SPREAD = 2.0
# 먼 쪽으로 건너뛸수록 드물다 (예전에는 어느 쪽이든 똑같았다)
JUMP_SCALE = 6.0


# 말끝·조사는 어느 페이지에나 나와서 유사도에 잡음만 준다
ENDINGS = ("습니다", "입니다", "합니다", "할게요", "갈게요", "볼게요", "에서는", "으로는", "거예요", "이에요", "예요",
           "해요", "어요", "아요", "에요", "게요", "니다", "으로", "에서", "에게", "까지", "부터", "하는", "하고",
           "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "요")
EN_STOP = {"the", "and", "of", "to", "in", "is", "it", "that", "this", "we", "you", "for", "on", "are", "be", "as", "so",
           "with", "can", "have", "if", "or", "an", "at", "by", "do", "not", "they", "there", "what", "which", "one",
           "will", "here", "just", "going", "get", "all", "about", "some", "also", "then", "these", "our", "your",
           "okay", "ok", "right", "now", "like", "want", "would", "how", "from", "has", "was", "its", "let", "use"}
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
    # FIND_IN_SET · DATE_ADD 같은 이름은 붙인 꼴(findinset)로도 센다: 받아쓰기는 붙여 쓰거나 한글로 적는다
    for joined in re.findall(r"[a-z0-9]+(?:_[a-z0-9]+)+", text):
        grams[joined.replace("_", "")] += 1
    for word in re.findall(r"[a-z0-9]+|[가-힣]+", text):
        if re.match(r"[a-z0-9]", word):
            if len(word) >= 2 and word not in EN_STOP:
                grams[word] += 1
        elif word not in FILLERS:
            word = _stem(word)
            grams.update(word[i:i + 2] for i in range(len(word) - 1))
    return grams


# ── 한글로 받아쓴 영어 용어 ("러닝 레이트")를 영어 슬라이드("learning rate")와 맞추기 ──
# 한국 대학 강의는 슬라이드는 영어, 말은 한국어인 경우가 많다. 받아쓰기는 영어 용어를 한글로 적으므로 글자가 하나도 안 겹친다.
# 두 쪽 모두 자음 뼈대(소리 갈래)로 바꿔서 같으면 같은 말로 본다: learning → L N N, 러닝 → L N N.
_CHO = "KKNTTLMPPSS_SSSKTPH"          # 첫소리 19개 (ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ), ㅇ은 소리 없음
_JONG = "_KKKNNNTLLLLLLLLMPPTTNTTKTPH"  # 끝소리 28개 (없음 포함), ㅇ 받침은 N (ng)
_LATIN = {"b": "P", "p": "P", "f": "P", "v": "P", "c": "K", "k": "K", "g": "K", "q": "K", "d": "T", "t": "T", "l": "L", "r": "L",
          "m": "M", "n": "N", "s": "S", "z": "S", "j": "S", "x": "KS", "h": "H", "w": "", "y": ""}
_VOWELS = "aeiou"


def hangul_skeleton(word: str) -> str:
    out = []
    for ch in word:
        code = ord(ch) - 0xAC00
        if not 0 <= code < 11172:
            return ""
        out.append(_CHO[code // 588])
        out.append(_JONG[code % 28])
    return _squash("".join(out))


def latin_skeleton(word: str) -> str:
    w = word.lower()
    w = re.sub(r"tion|sion|cian", "SN", w)          # ~션
    w = re.sub(r"ch|sh|th", "S", w).replace("ph", "P").replace("ck", "K").replace("ng", "N")
    w = re.sub(r"c(?=[eiy])", "S", w)               # descent → 디센트
    w = re.sub(r"g(?=[ei])", "S", w)                # gradient는 ㄱ이지만 algorithm·generation은 ㅈ: 둘 다 해 보기는 과해서 ㅈ 쪽만
    w = re.sub(r"(?<=[aeiou])r(?![aeiou])", "", w)  # 모음 뒤 r은 한글로 적을 때 사라진다 (learning → 러닝)
    w = re.sub(r"e$", "", w)
    out = []
    for ch in w:
        if ch in "SNPKTLMH":
            out.append(ch)
        elif ch not in _VOWELS:
            out.append(_LATIN.get(ch, ""))
    return _squash("".join(out))


def _squash(skeleton: str) -> str:
    skeleton = skeleton.replace("_", "")
    return re.sub(r"(.)\1+", r"\1", skeleton)


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
        # 슬라이드의 영어 낱말(5자 이상) → 자음 뼈대. 뼈대가 3 이상이고 한 낱말만 가리킬 때만 쓴다 (헛맞춤을 줄이려고)
        by_skeleton: dict[str, set[str]] = {}
        for word in df:
            if re.fullmatch(r"[a-z]{5,}", word):
                for skeleton in {latin_skeleton(word), latin_skeleton(word.replace("g", "k"))}:
                    if len(skeleton) >= 3:
                        by_skeleton.setdefault(skeleton, set()).add(word)
        self.sounds = {k: next(iter(v)) for k, v in by_skeleton.items() if len(v) == 1}
        self.korean = {w for t in page_texts for w in re.findall(r"[가-힣]{3,}", t)}

    def _spoken_english(self, text: str) -> Counter[str]:
        """말에 한글로 적힌 영어 용어 → 슬라이드의 영어 낱말"""
        found: Counter[str] = Counter()
        if not self.sounds:
            return found
        words = re.findall(r"[가-힣]+", text)
        # 띄어 쓴 영어 이름("파인드 인셋" = find_in_set): 이웃한 두세 낱말을 붙여서도 맞춰 본다
        for n in (3, 2):
            for i in range(len(words) - n + 1):
                hit = self.sounds.get(hangul_skeleton("".join(words[i:i + n])))
                if hit and len(hangul_skeleton("".join(words[i:i + n]))) >= 5:
                    found[hit] += 1
        for word in re.findall(r"[가-힣]{3,}", text):
            if word in self.korean:
                continue
            for cut in (0, 1, 2):  # 조사("레이트가", "디센트에서")를 떼어 가며
                stem = word[: len(word) - cut] if cut else word
                if len(stem) < 3:
                    break
                hit = self.sounds.get(hangul_skeleton(stem))
                if hit:
                    found[hit] += 1
                    break
        return found

    def _weigh(self, counts: Counter[str]) -> dict[str, float]:
        vec = {g: (1 + math.log(n)) * self.idf.get(g, 0.0) for g, n in counts.items() if g in self.idf}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {g: v / norm for g, v in vec.items()}

    def similarities(self, text: str) -> list[float]:
        grams = _grams(text)
        grams.update(self._spoken_english(text))
        query = self._weigh(grams)
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
    pinned: int | None = None   # 사용자가 '이 쪽 고정'을 누른 쪽: 풀 때까지 추정보다 우선

    def __post_init__(self) -> None:
        n = self.index.size
        # 강의는 보통 앞쪽에서 시작한다
        self.belief = [1.0 / n] * n if n else []
        if n:
            self.belief = _normalize([math.exp(-i / START_SPREAD) + 0.01 for i in range(n)])

    # 신호 A
    def user_viewed(self, page_no: int, now: float | None = None, manual: bool = True) -> None:
        """manual=False는 강의 시작 때 펴 둔 페이지처럼 직접 넘긴 게 아닌 경우: 약하게만 믿는다."""
        if 1 <= page_no <= self.index.size:
            self.user_page = page_no
            self.user_page_at = (time.monotonic() if now is None else now) if manual else -1e9

    def pin(self, page_no: int | None) -> None:
        """이 쪽 고정 (None 이면 풀기). 고정하는 동안 필기는 그 쪽에 붙고, 풀면 그 쪽에서부터 다시 추정한다"""
        self.pinned = page_no if page_no and 1 <= page_no <= self.index.size else None
        if self.pinned:
            self.belief = [1.0 if i == self.pinned - 1 else 0.0 for i in range(self.index.size)]

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
        if self.pinned:
            self.belief = [1.0 if i == self.pinned - 1 else 0.0 for i in range(n)]
            return Estimate(page_no=self.pinned, confidence=1.0, candidates=[self.pinned])
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
            far = [1.0 / (1.0 + abs(i - j) / JUMP_SCALE) if i != j else 0.0 for i in range(n)]
            total = sum(far) or 1.0
            row = [P_JUMP * f / total for f in far]
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
        said = int(number.group(1) or number.group(3)) if number else 0
        if 1 <= said <= n:
            prior[said - 1] += 0.6
        return _normalize(prior)


def _normalize(values: list[float]) -> list[float]:
    total = sum(values)
    return [v / total for v in values] if total > 0 else values


def best_block(blocks: list[dict], text: str, threshold: float = 0.12) -> dict | None:
    """받아쓰기 문장과 글자가 가장 많이 겹치는 문단. 충분히 겹치지 않으면 None (페이지 여백에 붙인다)."""
    query = _grams(text)
    qnorm = math.sqrt(sum(v * v for v in query.values())) or 1.0
    best, best_score = None, threshold
    for block in blocks:
        grams = _grams(block["text"])
        norm = math.sqrt(sum(v * v for v in grams.values())) or 1.0
        score = sum(n * grams.get(g, 0) for g, n in query.items()) / (qnorm * norm)
        if score > best_score:
            best, best_score = block, score
    return best
