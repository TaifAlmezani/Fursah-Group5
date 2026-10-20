import { expect, test, type Locator, type Page } from '@playwright/test';

const api = 'http://127.0.0.1:8018';
const endpoint = '/api/maintenance/requests';
const createResponse = (page: Page) => page.waitForResponse(r => r.url() === api + endpoint && r.request().method() === 'POST');
const resumeResponse = (page: Page) => page.waitForResponse(r => r.url().endsWith('/continue') && r.request().method() === 'POST');

test.beforeEach(async ({ page }) => { await page.goto('/'); });

test('happy path reaches real API and persisted SQLite ticket; actual trace renders in Arabic', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  const pending = createResponse(page);
  await page.getByRole('button', { name: 'بلاغ طبيعي' }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.status).toBe('success');
  await expect(page.getByText('تم إنشاء بلاغ الصيانة', { exact: true })).toBeVisible();
  await expect(page.locator('.result__ticket')).toHaveText(body.ticket.ticket_id);
  const ticket = await (await request.get(`${api}/__test__/tickets/${body.thread_id}`)).json();
  expect(ticket.ticket_id).toBe(body.ticket.ticket_id);
  expect(ticket.asset_id).toBe('AC-B12-02');
  expect(ticket.status).toBe(body.ticket.status);
  expect(ticket.recommended_action).toBe(body.recommended_action);
  expect(JSON.parse(ticket.recommendation_evidence).map((item: { procedure_id: string }) => item.procedure_id))
    .toEqual(body.evidence.map((item: { procedure_id: string }) => item.procedure_id));
  await expect(page.getByText('مرجع التوصية', { exact: true })).toBeVisible();
  expect(body.trace.every((step: { duration_ms: number }) => step.duration_ms >= 0)).toBe(true);
  await page.getByRole('button', { name: 'عرض مسار التنفيذ', exact: true }).click();
  await expect(page.locator('.trace')).toContainText('استخراج بيانات البلاغ');
  await expect(page.locator('.trace')).not.toContainText('extract_issue');
  await expect(page.locator('.trace')).toContainText(body.thread_id);
  expect(errors).toEqual([]);
});

test('missing location continues the same persisted workflow', async ({ page }) => {
  const initial = createResponse(page);
  await page.getByRole('button', { name: 'معلومات ناقصة' }).click();
  const first = await (await initial).json();
  expect(first.status).toBe('needs_information');
  await page.getByRole('textbox', { name: 'إجابة المتابعة' }).fill('B12');
  const resumed = resumeResponse(page);
  await page.getByRole('button', { name: 'متابعة ←' }).click();
  const last = await (await resumed).json();
  expect(last.status).toBe('success');
  expect(last.request_id).not.toBe(first.request_id);
  expect(last.thread_id).toBe(first.thread_id);
  await expect(page.getByText('تم إنشاء بلاغ الصيانة', { exact: true })).toBeVisible();
});

test('multiple clarification rounds keep the form active and preserve thread identity', async ({ page }) => {
  await page.getByRole('textbox', { name: 'وصف المشكلة' }).fill('جهاز فيه مشكلة');
  const initial = createResponse(page);
  await page.getByRole('button', { name: 'تحليل البلاغ ←' }).click();
  const first = await (await initial).json();
  for (const answer of ['B12', 'المكيف لا يعمل']) {
    await page.getByRole('textbox', { name: 'إجابة المتابعة' }).fill(answer);
    const pending = resumeResponse(page);
    await page.getByRole('button', { name: 'متابعة ←' }).click();
    const body = await (await pending).json();
    expect(body.thread_id).toBe(first.thread_id);
  }
  await expect(page.getByText('تم إنشاء بلاغ الصيانة', { exact: true })).toBeVisible();
});

test('ambiguous asset displays actual rooms and submits the chosen candidate', async ({ page }) => {
  await page.getByRole('button', { name: 'أكثر من جهاز' }).click();
  await expect(page.getByRole('radio')).toHaveCount(3);
  await expect(page.locator('.asset__room')).toHaveText(['301 — مبنى A — الدور 3', '305 — مبنى A — الدور 3', '310 — مبنى A — الدور 3']);
  await page.getByRole('radio', { name: /PR-305-01/ }).click();
  const pending = resumeResponse(page);
  await page.getByRole('button', { name: 'تأكيد الاختيار ←' }).click();
  const response = await pending;
  expect(response.request().postDataJSON()).toEqual({ input_type: 'asset_selection', asset_id: 'PR-305-01', step_id: expect.any(String) });
  const body = await response.json();
  expect(body.asset.asset_id).toBe('PR-305-01');
  await expect(page.locator('.result__sub')).toContainText('PR-305-01');
});

test('native asset radios support arrows, wrapping, Space and a single tab stop', async ({ page }) => {
  await page.getByRole('button', { name: 'أكثر من جهاز' }).click();
  const radios = page.getByRole('radio');
  await expect(radios).toHaveCount(3);
  await radios.nth(0).focus();
  await page.keyboard.press('Space');
  await expect(radios.nth(0)).toBeChecked();
  await page.keyboard.press('ArrowDown');
  await expect(radios.nth(1)).toBeFocused();
  await expect(radios.nth(1)).toBeChecked();
  await expect(radios.nth(0)).not.toBeChecked();
  await page.keyboard.press('ArrowDown');
  await expect(radios.nth(2)).toBeChecked();
  await page.keyboard.press('ArrowDown');
  await expect(radios.nth(0)).toBeChecked();
  await page.keyboard.press('ArrowUp');
  await expect(radios.nth(2)).toBeFocused();
  await expect(radios.nth(2)).toBeChecked();
  await expect(page.locator('.asset').nth(2)).toHaveCSS('outline-style', 'solid');
  await expect(radios.nth(2)).toHaveAccessibleName(/PR-310-01/);
  await page.keyboard.press('Tab');
  const confirm = page.getByRole('button', { name: 'تأكيد الاختيار ←' });
  await expect(confirm).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(radios.nth(2)).toBeFocused();
  await page.keyboard.press('Tab');
  const pending = resumeResponse(page);
  await page.keyboard.press('Enter');
  const response = await pending;
  expect(response.request().postDataJSON()).toEqual({ input_type: 'asset_selection', asset_id: 'PR-310-01', step_id: expect.any(String) });
  await expect(radios.nth(2)).toBeDisabled();
  await expect(radios.nth(2)).toBeChecked();
});

async function contrastMeasurements(locator: Locator, pseudo?: string) {
  return locator.evaluateAll((elements, pseudo) => elements.map(element => {
    const channels = (color: string) => color.match(/[\d.]+/g)!.map(Number);
    const luminance = (rgb: number[]) => rgb.slice(0, 3).map(value => {
      const c = value / 255;
      return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    }).reduce((sum, c, i) => sum + c * [0.2126, 0.7152, 0.0722][i], 0);
    const foreground = getComputedStyle(element, pseudo).color;
    let background = '';
    for (let parent: Element | null = element; parent; parent = parent.parentElement) {
      const color = getComputedStyle(parent).backgroundColor;
      if (channels(color)[3] !== 0) { background = color; break; }
    }
    const [low, high] = [luminance(channels(foreground)), luminance(channels(background))].sort((a, b) => a - b);
    return { text: element.textContent, foreground, background, ratio: (high + 0.05) / (low + 0.05) };
  }), pseudo);
}

test('secondary text contrast passes on normal, hovered and selected surfaces', async ({ page }, testInfo) => {
  const measurements = [];
  const initial = page.locator('.empty__eyebrow, .empty__label, .preset__loc, .composer-note, .tab__count');
  measurements.push(...await contrastMeasurements(initial));
  measurements.push(...await contrastMeasurements(page.getByRole('textbox', { name: 'وصف المشكلة' }), '::placeholder'));
  await page.getByRole('button', { name: 'أكثر من جهاز' }).hover();
  measurements.push(...await contrastMeasurements(page.getByRole('button', { name: 'أكثر من جهاز' }).locator('.preset__loc')));
  await page.getByRole('button', { name: 'أكثر من جهاز' }).click();
  await expect(page.getByRole('radio')).toHaveCount(3);
  measurements.push(...await contrastMeasurements(page.locator('.asset__desc, .asset__id, .step-summary')));
  await page.getByRole('radio').nth(1).hover();
  measurements.push(...await contrastMeasurements(page.locator('.asset').nth(1).locator('.asset__desc, .asset__id')));
  await page.getByRole('radio').nth(1).check();
  measurements.push(...await contrastMeasurements(page.locator('.asset.is-selected .asset__desc, .asset.is-selected .asset__id')));
  await page.getByRole('tab', { name: /مسار التنفيذ/ }).click();
  measurements.push(...await contrastMeasurements(page.locator('.trace__ids, .trace__ms, .trace__details, .tab__count')));
  expect(measurements.length).toBeGreaterThan(20);
  for (const measurement of measurements) {
    expect(measurement.ratio, JSON.stringify(measurement)).toBeGreaterThanOrEqual(4.5);
  }
  await testInfo.attach('browser-contrast.json', { body: JSON.stringify(measurements, null, 2), contentType: 'application/json' });
});

test('critical outcome renders server escalation and safety message', async ({ page }) => {
  const pending = createResponse(page);
  await page.getByRole('button', { name: 'حالة سلامة حرجة' }).click();
  const body = await (await pending).json();
  expect(body.status).toBe('critical');
  expect(body.ticket.status).toBe('escalated');
  await expect(page.locator('.result--danger')).toContainText(body.safety_message);
  await expect(page.locator('.ticket__stamp')).toHaveText('تم التصعيد');
});

test('asset not found creates no ticket', async ({ page, request }) => {
  const pending = createResponse(page);
  await page.getByRole('button', { name: 'جهاز غير مسجل' }).click();
  const body = await (await pending).json();
  expect(body.status).toBe('asset_not_found');
  await expect(page.locator('.ticket__stamp')).toHaveText('لم يُنشأ');
  expect(await (await request.get(`${api}/__test__/tickets/${body.thread_id}`)).json()).toBeNull();
});

test('real backend failure is contained and does not invite unsafe POST replay', async ({ page }) => {
  await expect(page.getByRole('button', { name: 'تعطل الخادم' })).toHaveCount(0);
  await page.getByRole('textbox', { name: 'وصف المشكلة' }).fill('اختبار فشل الاستخراج');
  const pending = createResponse(page);
  await page.getByRole('button', { name: 'تحليل البلاغ ←' }).click();
  expect((await pending).status()).toBe(500);
  await expect(page.locator('.result--error')).toBeVisible();
  await expect(page.locator('body')).not.toContainText('TEST_PRIVATE_BACKEND_ERROR');
  await expect(page.getByRole('button', { name: 'المحاولة مرة أخرى' })).toHaveCount(0);
});

test('pending submission blocks resetting and duplicates; no invented completed steps', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', r => { if (r.url() === api + endpoint && r.method() === 'POST') requests.push(r.url()); });
  await page.getByRole('button', { name: 'بلاغ طبيعي' }).evaluate((button: HTMLButtonElement) => {
    button.click(); button.click();
  });
  await expect(page.locator('.header__new')).toBeDisabled();
  await expect(page.locator('.live-steps .is-done')).toHaveCount(0);
  await expect(page.getByText('تم إنشاء بلاغ الصيانة', { exact: true })).toBeVisible();
  expect(requests).toHaveLength(1);
  await page.locator('.header__new').click();
  await expect(page.getByRole('textbox', { name: 'وصف المشكلة' })).toBeVisible();
  await expect(page.locator('.result')).toHaveCount(0);
});

test('client enforces backend input length limits', async ({ page }) => {
  await expect(page.getByRole('textbox', { name: 'وصف المشكلة' })).toHaveAttribute('maxlength', '4000');
  await page.getByRole('button', { name: 'معلومات ناقصة' }).click();
  await expect(page.getByRole('textbox', { name: 'إجابة المتابعة' })).toHaveAttribute('maxlength', '2000');
});

for (const status of [404, 409, 422, 500]) {
  test(`HTTP ${status} renders a controlled error without leaking response details`, async ({ page }) => {
    await page.route(`**${endpoint}`, route => route.fulfill({ status, json: {
      status: 'error', request_id: 'REQ-HTTP', message: 'SECRET_INTERNAL_EXCEPTION',
    } }));
    await page.getByRole('button', { name: 'بلاغ طبيعي' }).click();
    await expect(page.locator('.result--error')).toBeVisible();
    await expect(page.locator('body')).not.toContainText('SECRET_INTERNAL_EXCEPTION');
  });
}

for (const payload of [{ status: 'success' }, null, { status: 'unknown' }]) {
  test(`malformed response ${JSON.stringify(payload)} cannot crash rendering`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route(`**${endpoint}`, route => route.fulfill({ status: 200, json: payload }));
    await page.getByRole('button', { name: 'بلاغ طبيعي' }).click();
    await expect(page.locator('.result--error')).toBeVisible();
    expect(errors).toEqual([]);
  });
}

test('nullable backend values and skipped trace steps render safely', async ({ page }) => {
  await page.route(`**${endpoint}`, route => route.fulfill({ json: {
    status: 'success', request_id: 'REQ-NULL', thread_id: null,
    ticket: { ticket_id: 'MNT-NULL', status: 'created' },
    asset: { asset_id: 'AC-1', asset_type: 'air_conditioner', location: 'B12' },
    analysis: { category: null, priority: null, symptoms: [], safety_signals: [] },
    recommended_action: null,
    trace: [{ step: 'compose_recommendation', status: 'skipped', details: null, duration_ms: null }],
  } }));
  await page.getByRole('button', { name: 'بلاغ طبيعي' }).click();
  await expect(page.getByText('تم إنشاء بلاغ الصيانة', { exact: true })).toBeVisible();
  await expect(page.locator('.step-summary__item')).toContainText('–');
});

test('network loss is controlled and never automatically creates another request', async ({ page }) => {
  await page.route(`**${endpoint}`, route => route.abort('connectionfailed'));
  await page.getByRole('button', { name: 'بلاغ طبيعي' }).click();
  await expect(page.locator('.result--error')).toContainText('تعذر تأكيد نتيجة البلاغ');
  await expect(page.getByRole('button', { name: 'المحاولة مرة أخرى' })).toHaveCount(0);
});

test('mobile viewport retains usable form and no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('textbox', { name: 'وصف المشكلة' })).toBeVisible();
  const dimensions = await page.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
});

test('short desktop viewport can scroll to all presets without losing the composer', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 640 });
  await page.getByRole('button', { name: 'حالة سلامة حرجة' }).scrollIntoViewIfNeeded();
  await page.getByRole('button', { name: 'حالة سلامة حرجة' }).click();
  await expect(page.locator('.result--danger')).toBeVisible();
});

test('hazard warning stays visible while waiting for location', async ({ page }) => {
  await page.getByRole('textbox', { name: 'وصف المشكلة' }).fill('المكيف يهرب موية على اللوحة الكهربائية');
  const pending = createResponse(page);
  await page.getByRole('button', { name: 'تحليل البلاغ ←' }).click();
  const body = await (await pending).json();
  expect(body.status).toBe('needs_information');
  await expect(page.getByRole('alert')).toHaveText(body.safety_message);
  await expect(page.getByRole('textbox', { name: 'إجابة المتابعة' })).toBeVisible();
});

test('multi-hazard policy displays accumulated warnings and matches the saved escalation', async ({ page, request }) => {
  // The isolated server injects explicit extraction tags for this description.
  await page.getByRole('textbox', { name: 'وصف المشكلة' }).fill('اختبار سياسة المخاطر المتعددة');
  const initial = createResponse(page);
  await page.getByRole('button', { name: 'تحليل البلاغ ←' }).click();
  const first = await (await initial).json();
  expect(first.status).toBe('needs_information');
  await expect(page.getByRole('alert')).toHaveText(first.safety_message);
  await page.getByRole('textbox', { name: 'إجابة المتابعة' }).fill('B12');
  const resumed = resumeResponse(page);
  await page.getByRole('button', { name: 'متابعة ←' }).click();
  const last = await (await resumed).json();
  expect(last.status).toBe('critical');
  expect(last.analysis.priority).toBe('critical');
  expect(last.analysis.safety_signals).toEqual(['electrical_risk', 'fire_or_smoke']);
  expect(last.safety_message).toMatch(/^تحذير عالي الخطورة:/);
  expect(last.safety_message.split(first.safety_message)).toHaveLength(2);
  await expect(page.locator('.result--danger .c-danger-soft')).toHaveText(last.safety_message);
  const ticket = await (await request.get(`${api}/__test__/tickets/${last.thread_id}`)).json();
  expect(ticket.ticket_id).toBe(last.ticket.ticket_id);
  expect(ticket.safety_message).toBe(last.safety_message);
  expect(ticket.status).toBe('escalated');
});

test('missing SOP displays manual review without invented references', async ({ page }) => {
  await page.getByRole('button', { name: 'معلومات ناقصة' }).click();
  await page.getByRole('textbox', { name: 'إجابة المتابعة' }).fill('B12');
  const pending = resumeResponse(page);
  await page.getByRole('button', { name: 'متابعة ←' }).click();
  const body = await (await pending).json();
  expect(body.recommendation_status).toBe('manual_review');
  expect(body.evidence).toEqual([]);
  await expect(page.getByText('الفحص المطلوب', { exact: true })).toBeVisible();
  await expect(page.getByText('مرجع التوصية', { exact: true })).toHaveCount(0);
});

test('critical evidence renders electrical safety only', async ({ page }) => {
  const pending = createResponse(page);
  await page.getByRole('button', { name: 'حالة سلامة حرجة' }).click();
  const body = await (await pending).json();
  expect(body.evidence.every((item: { source: string }) => item.source === 'electrical.md')).toBe(true);
  await expect(page.locator('.result')).toContainText('السلامة الكهربائية');
  await expect(page.locator('.result')).not.toContainText('صينية التصريف');
});

for (const [status, code, message] of [
  [503, 'rag_unavailable', 'مراجع الصيانة غير جاهزة'],
  [503, 'model_unavailable', 'النموذج المحلي غير جاهز'],
  [502, 'invalid_model_output', 'تعذر فهم البلاغ'],
] as const) {
  test(`safe error distinguishes ${code}`, async ({ page }) => {
    await page.route(`**${endpoint}`, route => route.fulfill({ status, json: {
      status: 'error', request_id: 'REQ-FAIL', error_code: code, message: 'SECRET_INTERNAL_EXCEPTION',
    } }));
    await page.getByRole('button', { name: 'بلاغ طبيعي' }).click();
    await expect(page.locator('.result--error')).toContainText(message);
    await expect(page.locator('body')).not.toContainText('SECRET_INTERNAL_EXCEPTION');
  });
}
