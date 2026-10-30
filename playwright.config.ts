import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

const database = join(tmpdir(), `undercover-e2e-${String(Date.now())}.db`);

export default defineConfig({
  testDir: "e2e",
  outputDir: "e2e/test-results",
  reporter: "list",
  workers: 1,
  use: { baseURL: "http://localhost:5173" },
  webServer: [
    {
      command: "uv run -m uvicorn backend.main:app --port 8000",
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: false,
      env: {
        DB_PATH: database,
        AGENT_STUB: "1",
        VOICE_ENABLED: "1",
        VOICE_PROVIDER: "stub",
      },
    },
    {
      command: "npx vite dashboard --port 5173 --strictPort",
      url: "http://localhost:5173",
      reuseExistingServer: false,
    },
  ],
});
