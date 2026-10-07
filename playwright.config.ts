import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
const python =
  process.env.SERGEK_PYTHON ||
  (existsSync(".venv/Scripts/python.exe")
    ? resolve(".venv/Scripts/python.exe")
    : resolve("../../work/sergek-venv/Scripts/python.exe"));
export default defineConfig({
  testDir: "./tests/browser",
  use: {
    baseURL: "http://127.0.0.1:8765",
    channel: "msedge",
    viewport: { width: 1440, height: 1000 },
  },
  workers: 1,
  webServer: {
    command: `"${python}" tests/browser_server.py`,
    url: "http://127.0.0.1:8765/api/health",
    timeout: 90000,
    reuseExistingServer: false,
  },
});
