import { expect, test } from '@playwright/test';

test('mobile location field reaches the real API and completed ticket opens in an accessible sheet', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('textbox', { name: 'وصف المشكلة' }).fill('المكيف يهرب موية');
  await page.getByRole('textbox', { name: 'الموقع (اختياري)', exact: true }).fill('B12');
  const pending = page.waitForResponse(r => r.url().endsWith('/maintenance/requests') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'تحليل البلاغ ←' }).click();
  const response = await pending;
  expect(response.request().postDataJSON()).toEqual({ description: 'المكيف يهرب موية', location: 'B12' });
  const result = await response.json();
  await expect(page.locator('.result__ticket')).toHaveText(result.ticket.ticket_id);
  const trigger = page.getByRole('button', { name: 'تفاصيل البلاغ', exact: true });
  await trigger.click();
  const sheet = page.getByRole('dialog', { name: 'تفاصيل البلاغ' });
  await expect(sheet).toBeVisible();
  await expect(sheet.locator('.ticket__id')).toHaveText(result.ticket.ticket_id);
  expect(await page.evaluate(() => document.body.style.overflow)).toBe('hidden');
  await page.keyboard.press('Escape');
  await expect(sheet).not.toBeVisible();
  await expect(trigger).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden');
});

test('mobile device choice retains native keyboard behavior and trace opens from the completed result', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: 'أكثر من جهاز', exact: true }).click();
  const radios = page.getByRole('radio');
  await expect(radios.nth(0)).toBeFocused();
  await page.keyboard.press('ArrowDown');
  await expect(radios.nth(1)).toBeChecked();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'تأكيد الاختيار ←' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('.result__sub')).toContainText('PR-305-01');
  await page.getByRole('button', { name: 'عرض مسار التنفيذ', exact: true }).click();
  const sheet = page.getByRole('dialog');
  await expect(sheet.getByRole('tab', { name: /مسار التنفيذ/ })).toHaveAttribute('aria-selected', 'true');
  await expect(sheet.locator('.trace')).toContainText('مطابقة الأصل');
  await sheet.getByRole('button', { name: 'إغلاق تفاصيل البلاغ' }).click();
  await expect(sheet).not.toBeVisible();
  await expect(page.locator('.result--ok')).toBeVisible();
});

test('details sheet traps focus and tab arrows work without changing the report', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('textbox', { name: 'وصف المشكلة' }).fill('مسودة لم ترسل');
  await page.getByRole('button', { name: 'تفاصيل البلاغ', exact: true }).click();
  const sheet = page.getByRole('dialog');
  const ticketTab = sheet.getByRole('tab', { name: 'البلاغ', exact: true });
  await ticketTab.focus();
  await page.keyboard.press('ArrowLeft');
  await expect(sheet.getByRole('tab', { name: /مسار التنفيذ/ })).toBeFocused();
  await page.keyboard.press('Home');
  await expect(ticketTab).toBeFocused();
  for (let i = 0; i < 7; i++) {
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest('dialog')))).toBe(true);
  }
  await page.keyboard.press('Escape');
  await expect(page.getByRole('textbox', { name: 'وصف المشكلة' })).toHaveValue('مسودة لم ترسل');
});

test('switching between mobile sheet and desktop summary preserves selected tab and releases scroll lock', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: 'تفاصيل البلاغ', exact: true }).click();
  await page.getByRole('tab', { name: /مسار التنفيذ/ }).click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('aside.side')).toBeVisible();
  await expect(page.getByRole('tab', { name: /مسار التنفيذ/ })).toHaveAttribute('aria-selected', 'true');
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
});

test('phone, tablet and desktop layouts fit without horizontal scrolling or clipped form actions', async ({ page }) => {
  await page.goto('/');
  for (const [width, height] of [[320, 760], [390, 844], [768, 1024], [1024, 768], [1440, 1000], [1920, 1080]]) {
    await page.setViewportSize({ width, height });
    await expect(page.getByRole('textbox', { name: 'وصف المشكلة' })).toBeVisible();
    const dimensions = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth }));
    expect(dimensions.content, `${width}px viewport`).toBeLessThanOrEqual(dimensions.viewport);
    const button = await page.getByRole('button', { name: 'تحليل البلاغ ←' }).boundingBox();
    expect(button!.x).toBeGreaterThanOrEqual(0);
    expect(button!.x + button!.width).toBeLessThanOrEqual(width);
    expect(button!.height).toBeGreaterThanOrEqual(44);
  }
});

test('reduced motion preference removes loading animation and logo is available locally', async ({ page, request }) => {
  const logo = await request.get('/logo-white.svg');
  expect(logo.ok()).toBe(true);
  expect(await logo.text()).toContain('<svg');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await page.route('**/api/maintenance/requests', async route => {
    await new Promise(resolve => setTimeout(resolve, 800));
    await route.abort();
  });
  await page.getByRole('button', { name: 'بلاغ طبيعي', exact: true }).click();
  await expect(page.locator('.pulse')).toHaveCSS('animation-name', 'none');
});
