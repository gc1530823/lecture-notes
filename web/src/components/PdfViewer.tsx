// 앱 안에서 PDF 보기 (정리 노트 · 필기 붙은 슬라이드). 안드로이드 앱의 웹 화면은 PDF 를 직접 못 열어서 pdf.js 로 그린다.
import { useEffect, useRef, useState } from "react";
import { loadPdfUrl, renderPage, type PdfDoc } from "../lib/pdf";
import { Icon } from "./ui";

export function PdfViewer({ url, title, onClose }: { url: string; title: string; onClose: () => void }) {
  const [pdf, setPdf] = useState<PdfDoc | null>(null);
  const [error, setError] = useState("");
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    loadPdfUrl(url, url, true).then(setPdf).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [url]);
  useEffect(() => {
    if (!pdf || !body.current) return;
    const width = Math.min(body.current.clientWidth - 24, 820);
    let stop = false;
    (async () => {
      for (let n = 1; n <= pdf.numPages && !stop; n++) {
        const canvas = body.current?.querySelector<HTMLCanvasElement>(`canvas[data-page="${n}"]`);
        if (canvas) await renderPage(pdf, n, canvas, width).catch(() => undefined);
      }
    })();
    return () => { stop = true; };
  }, [pdf]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const download = url + (url.includes("?") ? "&" : "?") + "download=1";
  return (
    <div className="pdf-viewer" role="dialog" aria-label={title}>
      <header>
        <button className="top-bar-back" onClick={onClose} aria-label="닫기"><Icon name="x" /></button>
        <b className="grow">{title}</b>
        <a className="btn btn-primary pdf-dl" href={download} download><Icon name="download-simple" size={16} /> 내려받기</a>
      </header>
      <div className="pdf-pages" ref={body}>
        {error && <p className="muted">{error}</p>}
        {!pdf && !error && <p className="muted"><span className="spin" /> 여는 중…</p>}
        {pdf && Array.from({ length: pdf.numPages }, (_, i) => <canvas key={i} data-page={i + 1} />)}
      </div>
    </div>
  );
}
