// 강의자료 PDF를 그린다. pdf.js(Apache-2.0)는 public/vendor/pdfjs에 넣어 두고 필요할 때 한 번만 불러온다.
// 한글 PDF는 CID 글꼴을 많이 써서 문자표(cmaps)가 있어야 글자가 보인다.

interface PdfPage {
  getViewport(o: { scale: number }): { width: number; height: number };
  render(o: { canvasContext: CanvasRenderingContext2D; viewport: unknown }): { promise: Promise<void>; cancel(): void };
}
export interface PdfDoc { numPages: number; getPage(n: number): Promise<PdfPage> }
interface PdfJs {
  GlobalWorkerOptions: { workerSrc: string };
  getDocument(o: object): { promise: Promise<PdfDoc> };
}

const BASE = `${import.meta.env.BASE_URL}vendor/pdfjs/`;
let lib: Promise<PdfJs> | null = null;

function loadLib(): Promise<PdfJs> {
  lib ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = BASE + "pdf.min.js";
    s.onload = () => {
      const pdfjs = (window as unknown as { pdfjsLib: PdfJs }).pdfjsLib;
      pdfjs.GlobalWorkerOptions.workerSrc = BASE + "pdf.worker.min.js";
      resolve(pdfjs);
    };
    s.onerror = () => { lib = null; reject(new Error("PDF 보기 도구를 불러오지 못했어요")); };
    document.head.appendChild(s);
  });
  return lib;
}

const docs = new Map<string, Promise<PdfDoc>>();
export function loadPdf(docId: string): Promise<PdfDoc> {
  if (!docs.has(docId)) {
    const url = `${import.meta.env.VITE_API_URL ?? ""}/documents/${docId}/pdf`;
    const p = loadLib().then(async (pdfjs) => {
      const common = { cMapUrl: BASE + "cmaps/", cMapPacked: true, standardFontDataUrl: BASE + "standard_fonts/" };
      // 데모 빌드는 서버가 없어 미리 받아 둔 파일을 직접 읽어 넘긴다
      if (import.meta.env.VITE_DEMO === "1") {
        const data = new Uint8Array(await (await fetch(url)).arrayBuffer());
        return pdfjs.getDocument({ data, ...common }).promise;
      }
      return pdfjs.getDocument({ url, ...common }).promise;
    });
    p.catch(() => docs.delete(docId));
    docs.set(docId, p);
  }
  return docs.get(docId)!;
}

// 한 캔버스에 두 번 동시에 그리면 pdf.js가 오류를 내므로, 새로 그리기 전에 그리던 것을 멈춘다
const running = new WeakMap<HTMLCanvasElement, { cancel(): void }>();

export async function renderPage(pdf: PdfDoc, pageNo: number, canvas: HTMLCanvasElement, width: number) {
  running.get(canvas)?.cancel();
  const page = await pdf.getPage(pageNo);
  running.get(canvas)?.cancel();
  const base = page.getViewport({ scale: 1 });
  const ratio = Math.min(window.devicePixelRatio || 1, 3);
  const viewport = page.getViewport({ scale: (width / base.width) * ratio });
  // 크기를 바꾸면 캔버스가 지워지므로, 그리던 것을 멈춘 뒤에 바꾼다
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  const task = page.render({ canvasContext: canvas.getContext("2d")!, viewport });
  running.set(canvas, task);
  try {
    await task.promise;
  } catch (e) {
    if ((e as { name?: string })?.name !== "RenderingCancelledException") throw e;
  } finally {
    if (running.get(canvas) === task) running.delete(canvas);
  }
}
