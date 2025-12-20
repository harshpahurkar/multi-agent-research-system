import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 180_000,
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "retain-on-failure"
  },
  webServer: [
    {
      command: "python -m research_system",
      cwd: "..",
      port: 8002,
      reuseExistingServer: true,
      timeout: 120_000
    },
    {
      command: "npm.cmd run dev",
      port: 5174,
      reuseExistingServer: true,
      timeout: 120_000
    }
  ],
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } }
  ]
});
