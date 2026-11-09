// 1 자료 목록 (Figma "03 디자인 / 1 자료 목록")
import { useRef, useState } from "react";
import type { DocumentBrief } from "../api/types";
import { postJSON, useApi } from "../api/useApi";
import { Button, Chip, Empty, ListItem } from "../components/ui";
import { go } from "../router";

type Filter = "all" | "pdf" | "notebook";

export function subtitleOf(doc: DocumentBrief): string {
  const lectures = doc.sessions.length ? `강의 ${doc.sessions.length}번` : "아직 강의 없음";
  const kind = doc.kind === "notebook" ? `노트 · 주제 ${doc.page_count}개` : `슬라이드 ${doc.page_count}쪽`;
  return `${kind} · ${lectures} · ${relativeDay(doc.created_at)}`;
}

export function relativeDay(seconds: number): string {
  const days = Math.floor((Date.now() / 1000 - seconds) / 86400);
  if (days <= 0) return "오늘";
  if (days === 1) return "어제";
  if (days < 7) return `${days}일 전`;
  return new Date(seconds * 1000).toLocaleDateString("ko-KR", { month: "long", day: "numeric" });
}

export default function Home() {
  const { data: docs, error, loading, reload } = useApi<DocumentBrief[]>("/documents");
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);

  const upload = async (f: File) => {
    setBusy("강의자료를 읽는 중…");
    try {
      const form = new FormData();
      form.append("file", f);
      const res = await fetch((import.meta.env.VITE_API_URL ?? "") + "/documents", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail ?? "올리지 못했어요");
      await reload();
      go({ name: "doc", docId: data.id });
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const newNotebook = async () => {
    const title = prompt("수업 이름", "새 노트 수업");
    if (title === null) return;
    setBusy("노트를 만드는 중…");
    try {
      const doc = await postJSON<{ id: string }>("/documents/notebook", { title });
      go({ name: "doc", docId: doc.id });
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const shown = (docs ?? []).filter((d) => filter === "all" || (filter === "notebook" ? d.kind === "notebook" : d.kind !== "notebook"));
  const today = new Date().toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "long" });

  return (
    <div className="screen">
      <header className="home-head">
        <span className="t-caption muted">{today}</span>
        <h1 className="t-title-l">내 강의</h1>
      </header>
      <div className="screen-body">
        <div className="scroll-x" role="group" aria-label="자료 종류">
          {([["all", "전체"], ["pdf", "강의자료"], ["notebook", "노트"]] as const).map(([key, label]) => (
            <Chip key={key} variant={filter === key ? "selected" : "default"} onClick={() => setFilter(key)}>{label}</Chip>
          ))}
        </div>
        {loading && !docs && <p className="muted">불러오는 중…</p>}
        {error && <Empty icon="warning-circle">서버에 연결할 수 없어요<br /><span className="t-caption">{error}</span></Empty>}
        {docs && shown.length === 0 && (
          <Empty icon="chalkboard-teacher">
            <strong className="t-title-s">아직 강의가 없어요</strong><br />
            강의자료 PDF를 올리거나, 자료 없는 수업은 노트로 시작하세요.
          </Empty>
        )}
        {shown.map((doc) => (
          <ListItem key={doc.id} icon={doc.kind === "notebook" ? "notebook" : "file-pdf"} title={doc.title}
            subtitle={subtitleOf(doc)} onClick={() => go({ name: "doc", docId: doc.id })} />
        ))}
      </div>
      <div className="home-actions">
        <Button variant="secondary" icon="note-pencil" onClick={newNotebook} disabled={!!busy}>노트 수업</Button>
        <Button icon="tray-arrow-down" onClick={() => file.current?.click()} disabled={!!busy}>{busy ?? "강의자료 올리기"}</Button>
        <input ref={file} type="file" accept="application/pdf" hidden
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void upload(f); }} />
      </div>
    </div>
  );
}
