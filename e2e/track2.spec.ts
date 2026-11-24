import { test, expect, type Page } from '@playwright/test';

const domain = 'medical-ner-demo-v1';
const sourceText = 'John Smith works at Acme.';
const rows = [
  { label_id: 'L001', category: 'PERSON', annotator_id: 'ann-1', factors: { model_confidence: 0.9, item_difficulty: 0.2 }, confidence: 0.86, recommended_action: 'approve', text_preview: sourceText },
  { label_id: 'L002', category: 'PERSON', annotator_id: 'ann-2', factors: { model_confidence: 0.8, item_difficulty: 0.3 }, confidence: 0.72, recommended_action: 'reject', text_preview: 'Another source text' },
];

async function setAccount(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('rgi-api-key', 'browser-test-key');
    localStorage.setItem('rgi-domain', 'medical-ner-demo-v1');
  });
}

async function mockQueue(page: Page) {
  await setAccount(page);
  await page.route('**/v1/labels/*/pending*', async route => {
    const url = new URL(route.request().url());
    const offset = Number(url.searchParams.get('offset') ?? 0);
    await route.fulfill({ json: offset ? [] : rows, headers: { 'X-Total-Count': '2' } });
  });
  await page.route('**/v1/domains/*/autonomy', route => route.fulfill({
    json: { domain_id: domain, overall_tier: 'amber', categories: [{
      category: 'PERSON', tier: 'amber', verified_count: 0, accuracy: null,
      conservation_gate_pass: true, conservation_reason: null, next_tier: 'green',
      next_tier_requirements: 'More reviews', recommended_action_policy: 'confirm',
    }] },
  }));
}

async function mockReview(page: Page) {
  await mockQueue(page);
  await page.route('**/v1/labels/*/items/L001', route => route.fulfill({ json: {
    ...rows[0], domain_id: domain, text: sourceText, actual_action: null,
    verified_outcome: null, verified_at: null, revision_id: 'revision-1',
    previous_category: null, status: 'scored',
    content: { content_type: 'text_ner', spans: [
      { start: 0, end: 10, label: 'PERSON', text: 'John Smith' },
      { start: 20, end: 24, label: 'ORG', text: 'Acme' },
    ], tags: [], image_url: null },
  } }));
}

async function mockSample(page: Page) {
  await mockQueue(page);
  await page.route('**/demo/sample_data.json', route => route.fulfill({ json: {
    domain_id: domain,
    rows: Array.from({ length: 500 }, (_, index) => ({
      label_id: String(index), category: 'PERSON', annotator_id: 'ann-1',
      factor_model_confidence: 0.9, factor_item_difficulty: 0.2,
      verified_outcome: true, text: sourceText,
    })),
  } }));
  await page.route('**/v1/label-health/analyze', route => route.fulfill({ json: {
    metadata: { row_count: 500, verified_count: 500, factor_count: 2 }, warnings: [],
  } }));
  await page.route('**/v1/labels/*/sample', route => route.fulfill({
    json: { domain_id: domain, created: 12, existing: 0, pending: 12 },
  }));
}

async function clickSample(page: Page) {
  await page.goto('/#/upload');
  await page.getByRole('button', { name: 'Try with sample data' }).click();
  await expect(page.locator('.success')).toContainText('Analysis ready');
}

function unexpectedConsoleErrors(errors: string[]) {
  return errors.filter(error => !/React|DevTools|favicon|fetch|API|401|404/i.test(error));
}

test.describe('Track 2 signup', () => {
  test('signup page renders email form and submit button', async ({ page }) => {
    await page.goto('/#/signup');
    await expect(page.getByRole('textbox', { name: 'Email' })).toBeVisible();
    await expect(page.getByRole('button', { name: /Start Free Trial/i })).toBeVisible();
  });
  test('signup page shows the free trial call to action', async ({ page }) => {
    await page.goto('/#/signup');
    await expect(page.getByRole('heading', { name: /Start your free trial/i })).toBeVisible();
  });
  test('signup hash route is reachable', async ({ page }) => {
    await page.goto('/#/signup');
    expect(page.url()).toContain('#/signup');
    await expect(page.locator('form')).toBeVisible();
  });
  test('signup page loads without unexpected console errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.goto('/#/signup');
    await page.waitForTimeout(1000);
    expect(unexpectedConsoleErrors(errors)).toHaveLength(0);
  });
});

test.describe('Track 2 sample data', () => {
  test('upload offers sample data', async ({ page }) => {
    await page.goto('/#/upload');
    await expect(page.getByRole('button', { name: /sample/i })).toBeVisible();
  });
  test('sample click loads its analysis', async ({ page }) => {
    await mockSample(page);
    await clickSample(page);
    await expect(page.locator('.success')).toContainText('500 labels');
  });
  test('scoring the sample opens a populated queue', async ({ page }) => {
    await mockSample(page);
    await clickSample(page);
    await page.getByRole('button', { name: 'Score 12 sample labels' }).click();
    await expect(page).toHaveURL(/#\/queue$/);
    await expect(page.locator('tbody tr')).toHaveCount(2);
  });
});

test.describe('Track 2 settings', () => {
  test('settings hash route renders', async ({ page }) => {
    await page.goto('/#/settings');
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
  });
  test('settings displays API key and account panels', async ({ page }) => {
    await page.goto('/#/settings');
    await expect(page.getByRole('heading', { name: 'API key' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Account' })).toBeVisible();
  });
  test('settings loads without unexpected console errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.goto('/#/settings');
    await page.waitForTimeout(1000);
    expect(unexpectedConsoleErrors(errors)).toHaveLength(0);
  });
});

test.describe('Track 2 enhanced queue', () => {
  test('queue exposes working sort headers', async ({ page }) => {
    await mockQueue(page);
    await page.goto('/#/queue');
    const sort = page.getByRole('button', { name: 'Sort by Label ID' });
    await expect(sort).toBeVisible();
    await sort.click();
    await expect(sort).toContainText('↑');
  });
  test('queue shows pagination controls', async ({ page }) => {
    await mockQueue(page);
    await page.goto('/#/queue');
    await expect(page.getByRole('button', { name: 'Previous' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Next' })).toBeVisible();
  });
  test('queue reveals stored text preview', async ({ page }) => {
    await mockQueue(page);
    await page.goto('/#/queue');
    await expect(page.locator('tbody tr')).toHaveCount(2);
    await page.getByRole('checkbox', { name: 'Source preview' }).check();
    await expect(page.locator('tbody .preview-cell').first()).toContainText(sourceText);
  });
  test('queue has header and row bulk selection', async ({ page }) => {
    await mockQueue(page);
    await page.goto('/#/queue');
    await expect(page.locator('tbody tr')).toHaveCount(2);
    await expect(page.getByRole('checkbox', { name: 'Select all on this page' })).toBeVisible();
    await expect(page.getByRole('checkbox', { name: 'Select L001' })).toBeVisible();
  });
  test('selecting a row opens approve and reject actions', async ({ page }) => {
    await mockQueue(page);
    await page.goto('/#/queue');
    await page.getByRole('checkbox', { name: 'Select L001' }).check();
    const bar = page.getByRole('region', { name: 'Bulk review actions' });
    await expect(bar.getByRole('button', { name: 'Approve All' })).toBeVisible();
    await expect(bar.getByRole('button', { name: 'Reject All' })).toBeVisible();
  });
});

test.describe('Track 2 review card', () => {
  test('review card renders the exact source text', async ({ page }) => {
    await mockReview(page);
    await page.goto('/#/review/L001');
    await expect(page.getByRole('region', { name: 'Source text' })).toContainText(sourceText);
  });
  test('review card renders NER entity highlights', async ({ page }) => {
    await mockReview(page);
    await page.goto('/#/review/L001');
    await expect(page.locator('mark')).toHaveCount(2);
    await expect(page.locator('mark').first()).toContainText('John Smith');
  });
  test('review card offers category relabeling', async ({ page }) => {
    await mockReview(page);
    await page.goto('/#/review/L001');
    await expect(page.getByRole('combobox', { name: 'Choose category' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Relabel' })).toBeVisible();
  });
  test('A shortcut approves after a known outcome is selected', async ({ page }) => {
    await mockReview(page);
    let verified = false;
    await page.route('**/v1/labels/verify', async route => {
      const body = route.request().postDataJSON();
      verified = body.label_id === 'L001' && body.actual_action === 'approve' && body.verified_outcome === true;
      await route.fulfill({ json: { label_id: 'L001', action_taken: 'approve', was_correct: true, engine_updated: true, new_accuracy: 1 } });
    });
    await page.goto('/#/review/L001');
    await page.getByRole('combobox', { name: 'Known outcome' }).selectOption('correct');
    await page.getByRole('heading', { name: 'Review label' }).click();
    await page.keyboard.press('a');
    await expect(page).toHaveURL(/#\/review\/L002$/);
    expect(verified).toBe(true);
  });
});

test.describe('Track 2 signup banner', () => {
  test('upload shows signup banner without a key', async ({ page }) => {
    await page.addInitScript(() => localStorage.removeItem('rgi-api-key'));
    await page.goto('/#/upload');
    await expect(page.locator('.notice').filter({ hasText: /Start your free trial to score/i })).toBeVisible();
  });
  test('signup banner links to signup hash route', async ({ page }) => {
    await page.addInitScript(() => localStorage.removeItem('rgi-api-key'));
    await page.goto('/#/upload');
    const link = page.locator('.notice').getByRole('link', { name: /Start your free trial/i });
    await expect(link).toHaveAttribute('href', '/#/signup');
  });
});
