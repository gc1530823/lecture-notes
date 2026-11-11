"""공개 강의(재사용이 허락된 것, 예: MIT OpenCourseWare CC BY-NC-SA)에서 슬라이드 PDF·강의 영상·공식 자막을 찾아 내려받는다.

강의 페이지 HTML에서 링크를 찾는다: .pdf(슬라이드), .mp4(영상, archive.org 사본 포함), .srt/.vtt(자막).
유튜브 영상은 약관상 내려받지 않는다 (링크가 유튜브뿐이면 멈추고 알려 준다).

사용법: python scripts/fetch_open_lecture.py <슬라이드 페이지 또는 PDF 주소> <영상 페이지 또는 mp4 주소> <저장 폴더>
      python scripts/fetch_open_lecture.py --course <MIT OCW 과목 주소> <강의 번호> <저장 폴더>
      python scripts/fetch_open_lecture.py --today scripts/open_courses.txt <날짜 번호> <저장 폴더>   (매일 돌려 가며)
      python scripts/fetch_open_lecture.py --discover scripts/open_courses.txt                       (과목마다 가능한 강의)
"""

import html
import os
import re
import sys
import urllib.parse
import urllib.request

UA = {"User-Agent": "lecture-notes-test/1.0 (open courseware accuracy test)"}


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def links(page_url: str) -> list[str]:
    text = get(page_url).decode("utf-8", "replace")
    found = re.findall(r'(?:href|src|data-[a-z-]+)\s*=\s*"([^"]+)"', text)
    found += re.findall(r'https?://[^\s"\'<>]+', text)
    out = []
    for link in found:
        link = urllib.parse.urljoin(page_url, html.unescape(link))
        if link not in out:
            out.append(link)
    return out


def pick(candidates: list[str], exts: tuple[str, ...], prefer: str = "") -> str | None:
    hits = [c for c in candidates if urllib.parse.urlparse(c).path.lower().endswith(exts)]
    hits.sort(key=lambda c: (prefer.lower() not in c.lower(), len(c)))
    return hits[0] if hits else None


def download(url: str, path: str) -> None:
    print(f"  내려받기: {url}", flush=True)
    data = get(url)
    with open(path, "wb") as f:
        f.write(data)
    print(f"  → {path} ({len(data) / 1e6:.1f}MB)", flush=True)


def main(slides: str, video: str, out: str) -> None:
    os.makedirs(out, exist_ok=True)
    pdf = slides if slides.lower().endswith(".pdf") else pick(links(slides), (".pdf",), "lec")
    if not pdf:
        raise SystemExit(f"슬라이드 PDF 링크를 찾지 못했습니다: {slides}")
    download(pdf, os.path.join(out, "slides.pdf"))

    if video.lower().endswith(".mp4"):
        mp4, caption = video, None
    else:
        found = links(video)
        mp4 = pick(found, (".mp4",), "archive.org")
        caption = pick(found, (".srt", ".vtt"))
        if not mp4:
            youtube = [c for c in found if "youtube.com" in c or "youtu.be" in c][:3]
            raise SystemExit("내려받을 수 있는 mp4를 찾지 못했습니다" + (f" (유튜브 링크만 있음: {youtube})" if youtube else "")
                             + "\n찾은 링크 일부:\n" + "\n".join(found[:60]))
    download(mp4, os.path.join(out, "video.mp4"))
    if caption:
        download(caption, os.path.join(out, "captions" + os.path.splitext(urllib.parse.urlparse(caption).path)[1]))
    else:
        print("  공식 자막은 없었어요 (받아쓰기 정확도는 재지 않음)")


SLIDE_WORDS = ("slide", "lecture-notes", "lecture-note", "notes", "lecture-handouts", "handouts")
VIDEO_WORDS = ("video",)


def _course_pages(base: str) -> tuple[list[str], list[str]]:
    """과목 첫 페이지에서 '강의 슬라이드/노트' 페이지와 '강의 영상' 페이지 주소를 찾는다 (과목마다 이름이 다르다)."""
    found = [c for c in links(base + "/") if c.startswith(base) and ("/pages/" in c or "/video_galleries/" in c)]
    slides = [c for c in found if any(w in c.lower() for w in SLIDE_WORDS) and "video" not in c.lower()]
    videos = [c for c in found if any(w in c.lower() for w in VIDEO_WORDS)]
    # 흔한 이름은 첫 페이지에 링크가 없어도 직접 시도
    slides += [f"{base}/pages/{n}/" for n in ("lecture-slides-code", "lecture-slides", "lecture-notes", "lecture-notes-and-slides")]
    videos += [f"{base}/video_galleries/lecture-videos/", f"{base}/pages/lecture-videos/"]
    return list(dict.fromkeys(slides)), list(dict.fromkeys(videos))


def _gather(pages: list[str]) -> list[str]:
    out: list[str] = []
    for page in pages:
        try:
            out += [c for c in links(page) if c not in out]
        except Exception:  # 없는 페이지(404)는 건너뛴다
            pass
    return out


def find_lecture(base: str, number: int, slide_links: list[str], video_links: list[str]) -> tuple[str | None, str | None]:
    lec = re.compile(rf"(?:lec|lecture|ses|session)[-_ ]?0*{number}(?!\d)", re.I)
    pdf = next((c for c in slide_links if c.lower().endswith(".pdf") and lec.search(c.rsplit("/", 1)[-1])), None)
    if pdf is None:  # PDF가 리소스 페이지 뒤에 있는 과목
        pdf = next((c for c in slide_links if "/resources/" in c and "video" not in c and lec.search(c.split("/resources/")[1])), None)
    vid = re.compile(rf"/resources/(?:lecture|lec|session|ses)?-?0*{number}[-_]", re.I)
    video = next((c for c in video_links if vid.search(c)), None)
    return pdf, video


def course(base: str, number: int, out: str) -> None:
    """MIT OCW 과목 주소와 강의 번호로: 슬라이드/노트 목록에서 n번 PDF, 영상 목록에서 n번 강의 페이지를 찾는다."""
    base = base.rstrip("/")
    slide_pages, video_pages = _course_pages(base)
    pdf, video = find_lecture(base, number, _gather(slide_pages), _gather(video_pages))
    if not pdf or not video:
        raise SystemExit(f"{number}강을 찾지 못했습니다 (슬라이드 {pdf}, 영상 {video})")
    print(f"{number}강: 슬라이드 {pdf}\n      영상 {video}", flush=True)
    main(pdf, video, out)


def discover(list_file: str, max_lecture: int = 30) -> None:
    """과목 목록의 각 과목에서 슬라이드와 영상이 둘 다 있는 강의 번호를 찾아 보여 준다 (open_courses.txt를 고를 때)."""
    for base in read_courses(list_file):
        try:
            slide_pages, video_pages = _course_pages(base)
            sl, vl = _gather(slide_pages), _gather(video_pages)
            ok = [n for n in range(1, max_lecture + 1) if all(find_lecture(base, n, sl, vl))]
            print(f"{len(ok):2d}강 가능 {ok} · {base}", flush=True)
        except Exception as e:
            print(f" 실패 {type(e).__name__}: {e} · {base}", flush=True)


def read_courses(list_file: str) -> list[str]:
    with open(list_file, encoding="utf-8") as f:
        return [line.split("#")[0].strip().rstrip("/") for line in f if line.split("#")[0].strip()]


def pick_today(list_file: str, day: int, out: str, tries: int = 6) -> str:
    """날짜로 과목·강의를 돌려 고른다: 과목을 번갈아 가며, 같은 과목은 다음 강의로. 없으면 다음 후보로 넘어간다."""
    courses = read_courses(list_file)
    for t in range(tries):
        k = day + t
        base = courses[k % len(courses)]
        number = (k // len(courses)) % 24 + 1
        try:
            course(base, number, out)
            return f"{base.rsplit('/', 1)[-1][:40]}-lec{number}"
        except (SystemExit, Exception) as e:
            print(f"  건너뜀: {base} {number}강 ({e})", flush=True)
    raise SystemExit("오늘 쓸 강의를 찾지 못했습니다")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--course":
        course(sys.argv[2], int(sys.argv[3]), sys.argv[4])
    elif len(sys.argv) == 3 and sys.argv[1] == "--discover":
        discover(sys.argv[2])
    elif len(sys.argv) == 5 and sys.argv[1] == "--today":
        name = pick_today(sys.argv[2], int(sys.argv[3]), sys.argv[4])
        with open(os.path.join(sys.argv[4], "name.txt"), "w") as f:
            f.write(name)
    elif len(sys.argv) == 4:
        main(*sys.argv[1:])
    else:
        raise SystemExit(__doc__ + "\n또는: --course <과목 주소> <강의 번호> <저장 폴더>")
