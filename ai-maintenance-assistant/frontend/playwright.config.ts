import { defineConfig } from '@playwright/test';

const python = process.env.BACKEND_PYTHON ?? (process.platform === 'win32'
  ? '..\\backend\\.venv\\Scripts\\python.exe' : '../backend/.venv/bin/python');

export default defineConfig({
  testDir: '.', testMatch: ['**/tests/**/*.spec.ts', '**/qa/**/*.spec.ts'],
  timeout: 30_000, workers: 1, fullyParallel: false,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:5178', browserName: 'chromium',
    viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: [
    { command: `"${python}" ../backend/tests/browser_server.py`, url: 'http://127.0.0.1:8018/health',
      timeout: 120_000, reuseExistingServer: false },
    { command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5178 --strictPort',
      url: 'http://127.0.0.1:5178', timeout: 60_000, reuseExistingServer: false,
      env: { VITE_API_BASE_URL: 'http://127.0.0.1:8018/api', VITE_USE_MOCK: 'false' } },
  ],
});
