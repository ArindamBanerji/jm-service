import { test, expect, type Page } from '@playwright/test';

if (process.env.NER_EDITOR_BASE_URL) test.use({ baseURL: process.env.NER_EDITOR_BASE_URL });

const source = '😀 John Smith joined Acme <b>Ltd</b>.';
const original = { start: 2, end: 12, label: 'PERSON', text: 'John Smith' };

async function mockReview(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('rgi-api-key', 'ner-browser-key');
    localStorage.setItem('rgi-domain', 'medical');
  });
  let revision = 'revision-1';
  let spans = [original];
  let saved: Record<string, unknown> | null = null;
  await page.route('**/v1/labels/medical/items/L001/relabel', async route => {
    saved = route.request().postDataJSON();
    spans = (saved as { spans: typeof spans }).spans;
    revision = 'revision-2';
    await route.fulfill({ json: { label_id: 'L001', category: 'PERSON',
      revision_id: revision, previous_category: 'PERSON' } });
  });
  await page.route('**/v1/labels/medical/items/L001', route => route.fulfill({ json: {
    domain_id: 'medical', label_id: 'L001', category: 'PERSON', annotator_id: null,
    factors: { model_confidence: 0.7, item_difficulty: 0.2 },
    recommended_action: 'approve', confidence: 0.8, text: source,
    actual_action: null, verified_outcome: null, verified_at: null,
    revision_id: revision, previous_category: null, status: 'scored',
    content: { content_type: 'text_ner', spans, tags: [], image_url: null },
  } }));
  await page.route('**/v1/labels/medical/pending*', route => route.fulfill({ json: [], headers: { 'X-Total-Count': '0' } }));
  await page.route('**/v1/domains/medical/autonomy', route => route.fulfill({ json: {
    domain_id: 'medical', overall_tier: 'amber', categories: ['PERSON', 'ORG'].map(category => ({
      category, tier: 'amber', verified_count: 0, accuracy: null,
      conservation_gate_pass: true, conservation_reason: null, next_tier: 'green',
      next_tier_requirements: '', recommended_action_policy: 'confirm',
    })),
  } }));
  return { saved: () => saved };
}

test('selects Unicode text, creates a span, and saves a revision', async ({ page }) => {
  const mock = await mockReview(page);
  await page.goto('/#/review/L001');
  await expect(page.locator('section[aria-label="Edit named entities"]')).toBeVisible();
  await page.evaluate(() => {
    const root = document.querySelector('section[aria-label="Edit named entities"]')!;
    const textNode = [...root.querySelectorAll('[data-ner-text]')]
      .find(element => element.textContent?.includes('Acme'))!.firstChild!;
    const start = textNode.textContent!.indexOf('Acme');
    const range = document.createRange();
    range.setStart(textNode, start); range.setEnd(textNode, start + 4);
    window.getSelection()!.removeAllRanges(); window.getSelection()!.addRange(range);
    root.querySelector('.card-pad')!.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
  });
  await page.getByRole('dialog', { name: 'Choose entity type' }).getByRole('button', { name: 'ORG' }).click();
  await expect(page.getByText('Unsaved changes')).toBeVisible();
  await page.getByRole('button', { name: 'Save Spans' }).click();
  await expect(page.getByText('Spans saved.')).toBeVisible();
  expect((mock.saved() as { spans: typeof original[] }).spans).toEqual([
    original, { start: 20, end: 24, label: 'ORG', text: 'Acme' },
  ]);
});

test('changes a span type and deletes it', async ({ page }) => {
  await mockReview(page);
  await page.goto('/#/review/L001');
  await page.locator('mark[aria-label^="PERSON: John Smith"]').click();
  await page.getByRole('dialog', { name: 'Edit entity' }).getByRole('button', { name: 'ORG' }).click();
  await expect(page.locator('mark[aria-label^="ORG: John Smith"]')).toBeVisible();
  await page.locator('mark[aria-label^="ORG: John Smith"]').click();
  await page.getByRole('button', { name: 'Delete' }).click();
  await expect(page.locator('mark')).toHaveCount(0);
  await expect(page.getByText('Unsaved changes')).toBeVisible();
});
