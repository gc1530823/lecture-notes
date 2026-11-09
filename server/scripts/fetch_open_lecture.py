"""공개 강의(재사용이 허락된 것, 예: MIT OpenCourseWare CC BY-NC-SA)에서 슬라이드 PDF·강의 영상·공식 자막을 찾아 내려받는다.

강의 페이지 HTML에서 링크를 찾는다: .pdf(슬라이드), .mp4(영상, archive.org 사본 포함), .srt/.vtt(자막).
유튜브 영상은 약관상 내려받지 않는다 (링크가 유튜브뿐이면 멈추고 알려 준다).

사용법: python scripts/fetch_open_lecture.py <슬라이드 페이지 또는 PDF 주소> <영상 페이지 또는 mp4 주소> <저장 폴더>
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


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
