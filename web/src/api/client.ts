// 서버 API 클라이언트. 경로·요청 모양은 서버의 OpenAPI 명세에서 만든 타입(schema.d.ts)으로 검사한다.
// 서버 API를 바꾸면 `npm run api:sync`로 타입을 다시 만든다 (CI가 어긋났는지 확인한다).
import createClient from "openapi-fetch";
import type { paths } from "./schema";

export const api = createClient<paths>({ baseUrl: import.meta.env.VITE_API_URL ?? "" });
