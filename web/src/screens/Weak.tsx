// 약점 노트: 이 자료에서 퀴즈에 틀린 문제 · 수업 중 '모르겠어요' · 복습에서 자주 틀린 카드를 한곳에 (많이 틀린 것부터)
import { useEffect, useState } from "react";
import { getJSON } from "../api/useApi";
import { Button, Chip, Empty, TopBar } from "../components/ui";
import { back, go } from "../router";

interface Weak { card_key: string; source: string; front: string; back: string; page_no: number | null; lapses: number; reps: number }
const LABEL: Record<string, string> = { quiz: "퀴즈에서 틀림", confused: "수업 중 헷갈림", exam: "예상 문제", flashcard: "플래시카드" };

export function WeakScreen({ docId }: { docId: string }) {
  const [items, setItems] = useState<Weak[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { getJSON<Weak[]>(`/documents/${docId}/weak`).then(setItems).catch(() => setItems([])); }, [docId]);
  return (
    <div className="screen weak">
      <TopBar title="약점 노트" onBack={() => back({ name: "doc", docId })} />
      <div className="screen-body">
        <p className="t-caption muted" style={{ margin: "0 4px 12px" }}>퀴즈에서 틀린 문제와 수업 중 헷갈린 곳이에요. 복습에서 맞힐 때까지 다시 나와요.</p>
        {!items && <p className="muted">불러오는 중…</p>}
        {items && items.length === 0 && (
          <Empty icon="check-circle"><strong className="t-title-s">아직 약점이 없어요</strong><br />AI 퀴즈를 풀어 보거나 수업 중 '모르겠어요'를 누르면 여기에 모여요.</Empty>
        )}
        {items?.map((w) => (
          <button key={w.card_key} className={`weak-item${open === w.card_key ? " open" : ""}`} onClick={() => setOpen(open === w.card_key ? null : w.card_key)}>
            <span className="row" style={{ gap: 6 }}>
              <Chip variant="accent">{LABEL[w.source] ?? w.source}</Chip>
              {w.page_no ? <span className="t-caption faint">{w.page_no}쪽</span> : null}
              {w.lapses > 0 && <span className="t-caption weak-lapses">복습에서 {w.lapses}번 틀림</span>}
            </span>
            <b>{w.front}</b>
            {open === w.card_key ? <p>{w.back}</p> : <small>눌러서 답 보기</small>}
          </button>
        ))}
        {items && items.length > 0 && <Button block onClick={() => go({ name: "review" })}>복습하러 가기</Button>}
      </div>
    </div>
  );
}
