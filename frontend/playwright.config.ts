import path from 'node:path'
import { defineConfig, devices } from '@playwright/test'

// Smoke tests drive the built UI against the real demo backend: the synthetic
// inbox replays recorded model runs, so no API keys and no network are needed.
// Run `npm run build` first (`npm run e2e` does both). With E2E_BASE_URL set, the tests
// run against a server that is already up instead (CI points them at the Docker image).
const PORT = 8123
const external = process.env.E2E_BASE_URL
const db = path.join(import.meta.dirname, 'test-results', `demo-${Date.now()}.sqlite3`)

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: external ?? `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } }, testIgnore: /phone\.spec/ },
    { name: 'phone', use: { ...devices['Pixel 7'] }, testMatch: /phone\.spec/ },
  ],
  webServer: external ? undefined : {
    command: `uv run gmail-agent demo --port ${PORT}`,
    cwd: '..',
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      DEMO_DB_PATH: db,
      DEMO_REPLAY_SPEED: '0.1', // recorded latencies and the opening scenario run 10× faster
      WEB_DIST_DIR: path.join(import.meta.dirname, 'dist'),
    },
  },
})
