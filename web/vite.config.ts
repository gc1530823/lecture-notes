import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 중에는 FastAPI 서버(기본 8000번)로 API 요청을 넘긴다
const server = process.env.API_SERVER ?? "http://localhost:8000";
// /app 은 아직 옮기지 않은 실시간 녹음 화면(기존 웹앱)
const apiPaths = ["/documents", "/sessions", "/annotations", "/tasks", "/health", "/app"];

export default defineConfig({
  // 상대 경로로 만들어 서버의 /web 아래에서도, 개발 서버의 / 에서도 그대로 열리게 한다 (화면 이동은 # 주소라 괜찮다)
  base: "./",
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(apiPaths.map((p) => [p, { target: server, ws: true, changeOrigin: true }])),
  },
});
