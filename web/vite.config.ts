import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 중에는 FastAPI 서버(기본 8000번)로 API 요청을 넘긴다
const server = process.env.API_SERVER ?? "http://localhost:8000";
const apiPaths = ["/documents", "/sessions", "/annotations", "/tasks", "/health"];

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(apiPaths.map((p) => [p, { target: server, ws: true, changeOrigin: true }])),
  },
});
