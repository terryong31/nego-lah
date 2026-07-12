import { defineVitestConfig } from '@nuxt/test-utils/config'

// Every test runs inside a real (SPA-mode) Nuxt instance so auto-imports
// (useSupabaseClient, useRoute, navigateTo, useAsyncData, ...) resolve exactly
// like they do in the app, instead of hand-mocking dozens of globals per file.
// @nuxt/test-utils boots that instance from `.env.test` (not `.env`) by
// default — see frontend/.env.test for the dummy, safe values used in tests.
export default defineVitestConfig({
  test: {
    environment: 'nuxt',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'json-summary', 'lcov'],
      include: ['app/**/*.{ts,vue}'],
      exclude: [
        'app/types/**',
        '**/*.d.ts'
      ]
    }
  }
})
