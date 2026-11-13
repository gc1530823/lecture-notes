// 화면에서 쓰는 작은 데이터 훅. 서버 응답 모양은 types.ts에 적어 둔 타입으로 본다.
import { useCallback, useEffect, useState } from "react";

const BASE = import.meta.env.VITE_API_URL ?? "";

export async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new Error(await errorText(res));
  return res.json() as Promise<T>;
}

export async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errorText(res));
  return res.json() as Promise<T>;
}

async function errorText(res: Response): Promise<string> {
  if (res.status === 401) window.dispatchEvent(new Event("ln-login-needed"));
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") return data.detail;
  } catch { /* 본문이 JSON이 아니면 상태 코드로 */ }
  return `서버 오류 (${res.status})`;
}

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);

  const reload = useCallback(async () => {
    if (path === null) return;
    setLoading(true);
    try {
      setData(await getJSON<T>(path));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => { void reload(); }, [reload]);
  return { data, error, loading, reload, setData };
}
