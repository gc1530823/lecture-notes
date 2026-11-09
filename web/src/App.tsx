import { useEffect, useState } from "react";
import { api } from "./api/client";

// 새 프론트 자리: Figma 디자인이 나오면 화면을 이 위에 만든다. 지금은 서버 연동만 확인한다.
export default function App() {
  const [health, setHealth] = useState<string>("서버 확인 중…");

  useEffect(() => {
    api.GET("/health").then(({ data, error }) => {
      setHealth(error ? "서버에 연결할 수 없어요" : `서버 연결됨 · ${JSON.stringify(data)}`);
    });
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: 24 }}>
      <h1>강의노트 (새 프론트)</h1>
      <p>Figma 디자인을 바탕으로 만드는 중이에요.</p>
      <p>{health}</p>
    </main>
  );
}
