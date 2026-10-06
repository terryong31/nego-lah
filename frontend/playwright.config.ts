import { defineConfig, devices } from '@playwright/test'

// End-to-end checks against a running deployment (issue #14, SPEC-093/094).
//
//   E2E_BASE_URL  the SPA      (default http://localhost:3000)
//   E2E_API_URL   the API      (default http://localhost:8000)
//
// `smoke.e2e.ts` is anonymous and read-only, so it is safe against production.
// `session.e2e.ts` signs in, and is skipped unless E2E_EMAIL / E2E_PASSWORD are
// set for an account in that environment. Files end in `.e2e.ts`, not `.spec.ts`,
// so Vitest never collects them.
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
    trace: 'retain-on-failure'
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }]
})
