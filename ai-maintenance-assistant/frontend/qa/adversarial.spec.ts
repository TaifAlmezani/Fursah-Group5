import { expect, test } from '@playwright/test';

const api = 'http://127.0.0.1:8018';
const endpoint = '/api/maintenance/requests';
const completed = {
  status: 'success', request_id: 'REQ-QA', thread_id: 'th_qa',
  ticket: { ticket_id: 'TICK-QA', status: 'created' },
  asset: { asset_id: 'PL-7', asset_type: 'plumbing', location: '7', status: 'active' },
  analysis: { priority: 'high', category: 'Facilities & Plumbing', symptoms: ['water_leak'], safety_signals: ['flooding'] },
  recommended_action: 'يتطلب فحص فريق الصيانة.', recommendation_status: 'manual_review', evidence: [],
};

test.beforeEach(async ({ page }) => { await page.goto('/'); });

test('a noncritical API safety warning remains visible on a success card', async ({ page }) => {
  // Explicit contract fixture; the backend QA independently reproduces this status/priority.
  const warning = 'تحذير QA للتحقق من عرض التحذير غير المصعّد';
  await page.route(`**${endpoint}`, route => route.fulfill({ json: { ...completed, safety_message: warning } }));
  await page.getByRole('button', { name: 'بلاغ طبيعي' }).click();
  await expect(page.locator('.result--ok')).toBeVisible();
  await expect(page.locator('.result--ok')).toContainText(warning);
});

test('inconsistent success plus escalated ticket is rejected by the client contract', async ({ page }) => {
  await page.route(`**${endpoint}`, route => route.fulfill({ json: {
    ...completed, ticket: { ticket_id: 'TICK-QA', status: 'escalated' },
    analysis: { ...completed.analysis, priority: 'critical' }, safety_message: 'تحذير QA',
  } }));
  await page.getByRole('button', { name: 'بلاغ طبيعي' }).click();
  await expect(page.locator('.result--error')).toBeVisible();
});

test('a critical result with an empty safety warning is rejected', async ({ page }) => {
  await page.route(`**${endpoint}`, route => route.fulfill({ json: {
    ...completed, status: 'critical', ticket: { ticket_id: 'TICK-QA', status: 'escalated' },
    analysis: { ...completed.analysis, priority: 'critical' }, safety_message: '',
  } }));
  await page.getByRole('button', { name: 'بلاغ طبيعي' }).click();
  await expect(page.locator('.result--error')).toBeVisible();
});

test('HTML and JavaScript in user text render as text without executing', async ({ page }) => {
  const value = 'المكيف لا يعمل <img src=x onerror="window.__qaInjected=true">';
  await page.getByRole('textbox', { name: 'وصف المشكلة' }).fill(value);
  await page.getByRole('button', { name: 'تحليل البلاغ ←' }).click();
  await expect(page.locator('.msg-user__bubble')).toHaveText(value);
  await expect(page.getByRole('textbox', { name: 'إجابة المتابعة' })).toBeVisible();
  expect(await page.evaluate(() => (window as Window & { __qaInjected?: boolean }).__qaInjected)).toBeUndefined();
  await expect(page.locator('.msg-user__bubble img')).toHaveCount(0);
});

test('losing the response after server commit creates no automatic duplicate', async ({ page, request }) => {
  let savedResponse: typeof completed | undefined;
  let submissions = 0;
  await page.route(`**${endpoint}`, async route => {
    submissions += 1;
    const response = await route.fetch();
    savedResponse = await response.json();
    await route.abort('connectionfailed');
  });
  await page.getByRole('button', { name: 'بلاغ طبيعي' }).click();
  await expect(page.locator('.result--error')).toContainText('قد تكون المعالجة تمت');
  expect(submissions).toBe(1);
  expect(savedResponse?.thread_id).toBeTruthy();
  const ticket = await (await request.get(`${api}/__test__/tickets/${savedResponse!.thread_id}`)).json();
  expect(ticket.ticket_id).toBe(savedResponse!.ticket.ticket_id);
  await expect(page.getByRole('button', { name: 'المحاولة مرة أخرى' })).toHaveCount(0);
});

test('reloading a pending clarification preserves a way to continue the saved thread', async ({ page }) => {
  const initial = page.waitForResponse(response => response.url() === api + endpoint && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'معلومات ناقصة' }).click();
  const first = await (await initial).json();
  await expect(page.getByRole('textbox', { name: 'إجابة المتابعة' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('textbox', { name: 'إجابة المتابعة' })).toBeVisible();
  await page.getByRole('textbox', { name: 'إجابة المتابعة' }).fill('B12');
  const resumed = page.waitForResponse(response => response.url().endsWith('/continue') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'متابعة ←' }).click();
  const last = await (await resumed).json();
  expect(last.thread_id).toBe(first.thread_id);
  expect(last.status).toBe('success');
});

test('reload restores asset selection and a completed result using reads only', async ({ page }) => {
  let submissions = 0;
  page.on('request', request => { if (request.url().includes(endpoint) && request.method() === 'POST') submissions += 1; });
  await page.getByRole('button', { name: 'أكثر من جهاز' }).click();
  await expect(page.getByRole('radio')).toHaveCount(3);
  await page.reload();
  await expect(page.getByRole('radio')).toHaveCount(3);
  expect(submissions).toBe(1);
  await page.getByRole('radio', { name: /PR-305-01/ }).check();
  await page.getByRole('button', { name: 'تأكيد الاختيار ←' }).click();
  await expect(page.locator('.result--ok')).toBeVisible();
  const ticket = await page.locator('.result__ticket').textContent();
  await page.reload();
  await expect(page.locator('.result__ticket')).toHaveText(ticket!);
  expect(submissions).toBe(2);
});

test('reload sees a completion from another tab instead of answering a consumed step', async ({ page, request }) => {
  const initial = page.waitForResponse(response => response.url() === api + endpoint && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'معلومات ناقصة' }).click();
  const first = await (await initial).json();
  const completion = await request.post(`${api}${endpoint}/${first.thread_id}/continue`, {
    data: { input_type: 'text', text: 'B12', step_id: first.step_id },
  });
  expect(completion.ok()).toBe(true);
  const last = await completion.json();
  await page.reload();
  await expect(page.locator('.result__ticket')).toHaveText(last.ticket.ticket_id);
  await expect(page.getByRole('textbox', { name: 'إجابة المتابعة' })).toHaveCount(0);
});

test('restore waits for a busy thread with GET requests without replaying a POST', async ({ page }) => {
  let submissions = 0;
  page.on('request', request => { if (request.url().includes(endpoint) && request.method() === 'POST') submissions += 1; });
  const initial = page.waitForResponse(response => response.url() === api + endpoint && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'معلومات ناقصة' }).click();
  const first = await (await initial).json();
  await expect(page.getByRole('textbox', { name: 'إجابة المتابعة' })).toBeVisible();
  let reads = 0;
  await page.route(`**${endpoint}/${first.thread_id}`, route => {
    reads += 1;
    return reads <= 2 ? route.fulfill({ status: 409, json: { detail: 'busy' } }) : route.continue();
  });
  await page.reload();
  await expect(page.getByRole('textbox', { name: 'إجابة المتابعة' })).toBeVisible();
  expect(reads).toBeGreaterThanOrEqual(3);
  expect(submissions).toBe(1);
});

test('reload recovers a continuation committed before its response was lost', async ({ page }) => {
  await page.getByRole('button', { name: 'معلومات ناقصة' }).click();
  await expect(page.getByRole('textbox', { name: 'إجابة المتابعة' })).toBeVisible();
  let ticketId = '';
  let submissions = 0;
  await page.route('**/continue', async route => {
    submissions += 1;
    const response = await route.fetch();
    ticketId = (await response.json()).ticket.ticket_id;
    await route.abort('connectionfailed');
  });
  await page.getByRole('textbox', { name: 'إجابة المتابعة' }).fill('B12');
  await page.getByRole('button', { name: 'متابعة ←' }).click();
  await expect(page.locator('.result--error')).toContainText('قد تكون المعالجة تمت');
  await page.reload();
  await expect(page.locator('.result__ticket')).toHaveText(ticketId);
  expect(submissions).toBe(1);
});

test('extreme but contract-valid asset metadata fits its card at 320px', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 760 });
  await page.route(`**${endpoint}`, route => route.fulfill({ json: {
    status: 'needs_asset_selection', request_id: 'REQ-LONG', thread_id: 'th_long', step_id: 'step-long',
    message: 'اختر الجهاز', assets: [
      { asset_id: `ASSET-${'A'.repeat(1000)}`, asset_type: 'printer', location: `غرفة ${'ع'.repeat(1000)}`, status: 'active' },
    ],
  } }));
  await page.getByRole('button', { name: 'أكثر من جهاز' }).click();
  await expect(page.getByRole('radio')).toHaveCount(1);
  const geometry = await page.locator('.asset').evaluate(element => ({ width: element.clientWidth, content: element.scrollWidth }));
  await testInfo.attach('card-geometry.json', { body: JSON.stringify(geometry), contentType: 'application/json' });
  expect(geometry.content).toBeLessThanOrEqual(geometry.width + 1);
});

test('twenty immediate confirmation clicks send one continuation request', async ({ page }) => {
  let submissions = 0;
  page.on('request', request => { if (request.url().endsWith('/continue') && request.method() === 'POST') submissions += 1; });
  await page.getByRole('button', { name: 'أكثر من جهاز' }).click();
  await page.getByRole('radio', { name: /PR-305-01/ }).check();
  await page.getByRole('button', { name: 'تأكيد الاختيار ←' }).evaluate((button: HTMLButtonElement) => {
    for (let i = 0; i < 20; i += 1) button.click();
  });
  await expect(page.locator('.result--ok')).toBeVisible();
  expect(submissions).toBe(1);
});

test('missing continuation thread identity is rejected without presenting a follow-up', async ({ page }) => {
  await page.route(`**${endpoint}`, route => route.fulfill({ json: {
    status: 'needs_information', request_id: 'REQ-QA', step_id: 'step-qa', question: 'وين الموقع؟', missing_fields: ['location'],
  } }));
  await page.getByRole('button', { name: 'بلاغ طبيعي' }).click();
  await expect(page.locator('.result--error')).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'إجابة المتابعة' })).toHaveCount(0);
});
