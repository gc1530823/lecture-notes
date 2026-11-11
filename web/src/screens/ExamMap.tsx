// 5 시험 예상 지도: 쪽마다 진하기 = 교수님이 시험·강조를 말한 정도
import type { ExamMap as ExamMapData } from "../api/types";
import { useApi } from "../api/useApi";
import { Empty, ListItem, TopBar } from "../components/ui";
import { go } from "../router";

export default function ExamMap({ docId }: { docId: string }) {
  const { data, error } = useApi<ExamMapData>(`/documents/${docId}/exam-map`);

  return (
    <div className="screen">
      <TopBar title="시험 예상 지도" onBack={() => go({ name: "doc", docId })} />
      <div className="screen-body">
        {error && <Empty icon="warning-circle">{error}</Empty>}
        {data && data.lectures === 0 && <Empty icon="target">강의를 한 번 이상 녹음하면 지도가 생겨요</Empty>}
        {data && data.lectures > 0 && (
          <>
            <p className="t-caption muted">강의 {data.lectures}번 · 교수님이 강조한 쪽일수록 진해요</p>
            <div className="heat-grid" role="list">
              {data.pages.map((p) => (
                <div key={p.page_no} role="listitem" className="heat-cell" data-i={p.page_no} title={p.reasons.join(", ") || "언급 적음"}
                  aria-label={`${p.page_no}쪽 ${p.level === "high" ? "유력" : p.level === "medium" ? "보통" : "낮음"}`}
                  style={{
                    animationDelay: `${Math.min(p.page_no, 30) * 25}ms`,
                    background: `color-mix(in srgb, var(--note-exam-ink) ${Math.round(8 + p.score * 85)}%, transparent)`,
                    color: p.score > 0.55 ? "var(--text-on-accent)" : "var(--text-primary)",
                  }}>
                  {p.page_no}
                </div>
              ))}
            </div>
            <h2 className="t-title-s section-title">가장 유력한 곳</h2>
            {data.top.length === 0 && <p className="muted">아직 두드러진 쪽이 없어요.</p>}
            {data.top.map((no) => {
              const p = data.pages.find((x) => x.page_no === no);
              return <ListItem key={no} icon="fire" title={`${no}쪽`} subtitle={p?.reasons.join(" · ")} />;
            })}
          </>
        )}
      </div>
    </div>
  );
}
