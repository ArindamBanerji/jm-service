import { test, expect, type Page } from '@playwright/test';

test.use({ baseURL: process.env.TAG_IMAGE_BASE_URL ?? 'http://localhost:8080' });

async function mockReview(page: Page, content: Record<string, unknown>, text: string | null) {
  await page.addInitScript(() => {
    localStorage.setItem('rgi-api-key', 'tag-browser-key');
    localStorage.setItem('rgi-domain', 'medical');
  });
  let revision = 'revision-1';
  let currentContent = content;
  let saved: Record<string, unknown> | null = null;
  await page.route('**/v1/labels/medical/items/item-1/relabel', async route => {
    saved = route.request().postDataJSON();
    revision = 'revision-2';
    currentContent = { ...currentContent, tags: (saved as { tags: string[] }).tags };
    await route.fulfill({ json: { label_id: 'item-1', category: 'SENTIMENT', revision_id: revision, previous_category: null } });
  });
  await page.route('**/v1/labels/medical/items/item-1', route => route.fulfill({ json: {
    domain_id: 'medical', label_id: 'item-1', category: 'SENTIMENT', annotator_id: null,
    factors: { model_confidence: 0.7, item_difficulty: 0.2 },
    recommended_action: 'approve', confidence: 0.8, text,
    actual_action: null, verified_outcome: null, verified_at: null,
    revision_id: revision, previous_category: null, status: 'scored', content: currentContent,
  } }));
  await page.route('**/v1/labels/medical/pending*', route => route.fulfill({ json: [], headers: { 'X-Total-Count': '0' } }));
  await page.route('**/v1/domains/medical/autonomy', route => route.fulfill({ json: {
    domain_id: 'medical', overall_tier: 'amber', categories: ['SENTIMENT', 'URGENT'].map(category => ({
      category, tier: 'amber', verified_count: 0, accuracy: null,
      conservation_gate_pass: true, conservation_reason: null, next_tier: 'green',
      next_tier_requirements: '', recommended_action_policy: 'confirm',
    })),
  } }));
  return { saved: () => saved };
}

test('tag autocomplete, custom entry, duplicate guard, removal, and save', async ({ page }) => {
  const mock = await mockReview(page, { content_type: 'text_multilabel', spans: [],
    tags: ['positive'], image_url: null }, 'The product arrived quickly.');
  await page.goto('/#/review/item-1');
  const input = page.getByRole('combobox', { name: 'Add tag' });
  await input.fill('urg');
  await page.getByRole('region', { name: 'Multi-label tags' }).getByRole('option', { name: 'URGENT' }).click();
  await input.fill('urgent'); await input.press('Enter');
  await expect(page.getByRole('button', { name: 'Remove URGENT' })).toHaveCount(1);
  await input.fill('custom'); await input.press('Enter');
  await expect(page.getByRole('button', { name: 'Remove custom' })).toBeVisible();
  await input.press('Backspace');
  await expect(page.getByRole('button', { name: 'Remove custom' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Save Tags' }).click();
  await expect(page.getByText('Tags saved.')).toBeVisible();
  expect((mock.saved() as { tags: string[] }).tags).toEqual(['positive', 'URGENT']);
});

test('image viewer reports a broken image and keeps category controls', async ({ page }) => {
  await mockReview(page, { content_type: 'image_classification', spans: [], tags: [],
    image_url: 'https://images.example.test/broken.png' }, null);
  await page.route('https://images.example.test/broken.png', route => route.abort());
  await page.goto('/#/review/item-1');
  await expect(page.getByRole('alert').filter({ hasText: 'Image not available' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Category' })).toBeVisible();
});
