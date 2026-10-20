import { defineConfig } from '@playwright/test';
import base from './playwright.config';

export default defineConfig({
  ...base,
  testDir: './qa',
  timeout: 15_000,
  outputDir: './test-results/qa',
  reporter: [['list'], ['json', { outputFile: './test-results/qa/results.json' }],
    ['html', { outputFolder: './qa-report', open: 'never' }]],
});
