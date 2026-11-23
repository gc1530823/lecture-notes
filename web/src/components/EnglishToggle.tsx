// '영어 강의' 체크: 처음에 체크하면 받아쓰기를 영어로 고정한다 (안 하면 목소리를 듣고 언어를 고른다).
// 강의자료마다 기억해 두어 다음 녹음에도 그대로. 새 노트(강의자료 없이)는 'new' 칸에.
import { useState } from "react";
import { Icon } from "./ui";

const key = (docId: string | null) => `ln.lang.${docId ?? "new"}`;

export function lectureLang(docId: string | null): "en" | "" {
  try { return localStorage.getItem(key(docId)) === "en" ? "en" : ""; } catch { return ""; }
}

export function setLectureLang(docId: string | null, en: boolean) {
  try { if (en) localStorage.setItem(key(docId), "en"); else localStorage.removeItem(key(docId)); } catch { /* 괜찮다 */ }
}

export function EnglishToggle({ docId, onChange }: { docId: string | null; onChange?: (en: boolean) => void }) {
  const [en, setEn] = useState(() => lectureLang(docId) === "en");
  const flip = () => { const next = !en; setEn(next); setLectureLang(docId, next); onChange?.(next); };
  return (
    <button type="button" className={`lang-toggle${en ? " on" : ""}`} role="switch" aria-checked={en} onClick={flip}>
      <span className="lang-box">{en && <Icon name="check" size={12} />}</span>
      <span className="grow"><b>영어 강의예요</b><small>{en ? "영어로 받아써요" : "자동으로 언어 감지"}</small></span>
      <span className="lang-tag">EN</span>
    </button>
  );
}
