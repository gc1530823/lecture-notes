// 자료 상세: 강의(녹음) 목록과 수업 시작, 시험 예상 지도로 가는 곳
import type { DocumentBrief } from "../api/types";
import { useApi } from "../api/useApi";
import { Button, Empty, ListItem, TopBar } from "../components/ui";
import { go } from "../router";
import { subtitleOf } from "./Home";

const STATUS: Record<string, string> = { recording: "녹음 중", processing: "정리 중", done: "정리 끝" };

export default function DocDetail({ docId }: { docId: string }) {
  // 목록 API에 강의 목록이 같이 오므로 그것을 쓴다
  const { data: docs, error } = useApi<DocumentBrief[]>("/documents");
  const doc = docs?.find((d) => d.id === docId);

  return (
    <div className="screen">
      <TopBar title={doc?.title ?? "강의"} onBack={() => go({ name: "home" })} />
      <div className="screen-body">
        {error && <Empty icon="warning-circle">{error}</Empty>}
        {docs && !doc && <Empty icon="warning">자료를 찾을 수 없어요</Empty>}
        {doc && (
          <>
            <p className="t-caption muted">{subtitleOf(doc)}</p>
            {/* 실시간 녹음 화면은 아직 기존 웹앱(/app)에 있다. 옮기기 전까지 그쪽으로 보낸다 */}
            <Button block variant="record" icon="microphone" onClick={() => { window.location.href = `/app/#/lecture/${doc.id}`; }}>
              수업 시작
            </Button>
            {doc.kind !== "notebook" && (
              <ListItem icon="target" title="시험 예상 지도" subtitle="여러 강의에서 교수님이 강조한 쪽을 모아 봐요"
                onClick={() => go({ name: "exam", docId })} />
            )}
            <h2 className="t-title-s section-title">지난 강의</h2>
            {doc.sessions.length === 0 && <p className="muted">아직 녹음한 강의가 없어요.</p>}
            {doc.sessions.map((s, i) => (
              <ListItem key={s.id} icon="headphones"
                title={new Date(s.started_at * 1000).toLocaleString("ko-KR", { month: "long", day: "numeric", weekday: "short", hour: "numeric", minute: "2-digit" })}
                subtitle={`${doc.sessions.length - i}번째 강의 · ${STATUS[s.status] ?? s.status}`}
                onClick={() => go({ name: "session", docId, sessionId: s.id, tab: "notes" })} />
            ))}
          </>
        )}
      </div>
    </div>
  );
}
