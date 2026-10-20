// Verify the actually served component without creating maintenance records.
// API replies are explicit fixtures; page source comes from the supplied URL.
import { chromium, expect } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';

const url = process.argv[2] ?? 'http://localhost:5173';
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const assets = ['301', '305', '310'].map(room => ({
  asset_id: `PR-${room}-01`, asset_type: 'printer', location: `${room} — مبنى A — الدور 3`,
  model: `Demo-Printer-${room}`, status: 'active',
}));
let submitted;
try {
  await page.route('**/api/maintenance/requests', route => route.fulfill({ json: {
    status: 'needs_asset_selection', request_id: 'REQ-KEYBOARD', thread_id: 'th_keyboard_qa', step_id: 'step-keyboard',
    message: 'تم العثور على أكثر من جهاز في هذا الموقع، يرجى اختيار الجهاز المتعطل.', assets, trace: [],
  } }));
  await page.route('**/continue', route => {
    submitted = route.request().postDataJSON();
    return route.fulfill({ json: {
      status: 'success', request_id: 'REQ-KEYBOARD-DONE', thread_id: 'th_keyboard_qa',
      asset: assets.find(asset => asset.asset_id === submitted.asset_id),
      ticket: { ticket_id: 'TICK-KEYBOARD-QA', status: 'created' },
      analysis: { category: 'IT Equipment', priority: 'medium', symptoms: ['paper_jam'], safety_signals: [] },
      recommended_action: 'نتيجة اختبار واجهة مع بيانات محاكاة.', recommendation_status: 'manual_review', evidence: [], trace: [],
    } });
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'أكثر من جهاز' }).click();
  const radios = page.getByRole('radio');
  await expect(radios).toHaveCount(3);
  expect(await radios.nth(0).evaluate(element => element.tagName)).toBe('INPUT');
  await expect(radios.nth(0)).toBeFocused();
  await page.keyboard.press('Space');
  await expect(radios.nth(0)).toBeChecked();
  await page.keyboard.press('ArrowDown');
  await expect(radios.nth(1)).toBeChecked();
  await page.keyboard.press('ArrowUp');
  await expect(radios.nth(0)).toBeChecked();
  await page.keyboard.press('ArrowLeft');
  const left = await page.locator('input[type=radio]:checked').inputValue();
  expect(left).not.toBe('PR-301-01');
  await page.keyboard.press('ArrowRight');
  await expect(radios.nth(0)).toBeChecked();
  await page.keyboard.press('ArrowUp');
  await expect(radios.nth(2)).toBeChecked();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'تأكيد الاختيار ←' })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(radios.nth(2)).toBeFocused();
  await page.keyboard.press('ArrowUp');
  await expect(radios.nth(1)).toBeChecked();
  await mkdir('../docs/qa', { recursive: true });
  await page.screenshot({ path: '../docs/qa/live-keyboard-5173.png' });
  await page.keyboard.press('Tab');
  await page.keyboard.press('Enter');
  await expect(page.locator('.result--ok')).toBeVisible();
  expect(submitted.asset_id).toBe('PR-305-01');
  const report = { url, passed: true, source: 'live served page', api: 'explicit intercepted fixtures; no real records created',
    checks: ['native input', 'automatic focus', 'Space', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'wrapping', 'Tab', 'Shift+Tab', 'confirmed asset'], submitted };
  await writeFile('../docs/qa/live-keyboard-5173.json', JSON.stringify(report, null, 2));
  process.stdout.write(JSON.stringify(report) + '\n');
} finally {
  await context.close();
  await browser.close();
}
