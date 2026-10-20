import { chromium, expect } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';

const root = '../docs/qa/ui-refresh';
const url = process.argv[2] ?? 'http://localhost:5173';
await mkdir(root, { recursive: true });
const browser = await chromium.launch();
const cases = [];
try {
  for (const [name, width, height] of [['desktop', 1440, 1060], ['phone', 390, 844], ['small-phone', 320, 760], ['tablet', 768, 1024], ['laptop', 1024, 768]]) {
    const context = await browser.newContext({ viewport: { width, height }, reducedMotion: 'reduce' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(url);
    await page.evaluate(() => document.fonts.ready);
    await expect(page.getByRole('textbox', { name: 'وصف المشكلة' })).toBeVisible();
    await page.screenshot({ path: `${root}/${name}-home.png`, fullPage: true });
    const geometry = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth }));
    expect(geometry.content).toBeLessThanOrEqual(width);
    cases.push({ name, width, height, geometry, errors });
    if (name === 'desktop' || name === 'phone') {
      const assets = ['301', '305', '310'].map(room => ({ asset_id: `PR-${room}-01`, asset_type: 'printer', location: `${room} — مبنى A — الدور 3`, model: `Demo-Printer-${room}`, status: 'active' }));
      await page.route('**/api/maintenance/requests', route => route.fulfill({ json: { status: 'needs_asset_selection', request_id: 'REQ-UI', thread_id: 'th_ui_preview', step_id: 'step-ui', message: 'تم العثور على أكثر من جهاز في هذا الموقع، يرجى اختيار الجهاز المتعطل.', assets, trace: [] } }));
      await page.getByRole('button', { name: 'أكثر من جهاز', exact: true }).click();
      await expect(page.getByRole('radio')).toHaveCount(3);
      await page.getByRole('radio').nth(1).check();
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
      await page.screenshot({ path: `${root}/${name}-selection.png`, fullPage: true });
      if (name === 'phone') {
        await page.getByRole('button', { name: 'تفاصيل البلاغ', exact: true }).click();
        await expect(page.getByRole('dialog')).toBeVisible();
        await page.screenshot({ path: `${root}/phone-details.png` });
        await page.keyboard.press('Escape');
      }
      await page.route('**/continue', route => route.fulfill({ json: {
        status: 'success', request_id: 'REQ-UI-DONE', thread_id: 'th_ui_preview', asset: assets[1],
        ticket: { ticket_id: 'TICK-UI-PREVIEW', status: 'created' },
        analysis: { priority: 'medium', category: 'printing', symptoms: ['paper_jam'], safety_signals: [] },
        recommended_action: 'فحص مسار الورق وتحديد سبب الانحشار بواسطة فريق الصيانة.', recommendation_status: 'manual_review', evidence: [], trace: [],
      } }));
      await page.getByRole('button', { name: 'تأكيد الاختيار ←' }).click();
      await expect(page.locator('.result--ok')).toBeVisible();
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
      await page.screenshot({ path: `${root}/${name}-success.png`, fullPage: true });
    }
    expect(errors).toEqual([]);
    await context.close();
  }
  await writeFile(`${root}/visual-checks.json`, JSON.stringify({ url, api: 'intercepted fixtures; no live maintenance records created', cases }, null, 2));
  console.log(JSON.stringify({ screenshots: root, viewports: cases.length, passed: true }));
} finally { await browser.close(); }
