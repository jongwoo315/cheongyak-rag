import { defineConfig } from "@playwright/test";

// 띄워 둔 서버를 쓴다 (Next.js 3184 · FastAPI 8171). WEB_BASE_URL로 바꾼다.
export default defineConfig({
  testDir: "./e2e",
  timeout: 30 * 60 * 1000,
  workers: 1,
  reporter: "list",
  use: { baseURL: process.env.WEB_BASE_URL ?? "http://127.0.0.1:3184" },
});
