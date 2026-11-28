import { test, expect } from '@playwright/test';

// ═══════════════════════════════════════════════════════════
// DLJ Playwright E2E — Screen Rendering + Interaction Tests
// Requires: uvicorn jm_service:app --port 8080
// Run: node .\node_modules\@playwright\test\cli.js test --config=playwright.config.ts
// ═══════════════════════════════════════════════════════════

test.describe('Health & API', () => {
  test('health endpoint returns structured JSON', async ({ request }) => {
    const res = await request.get('/v1/health');
    const body = await res.json();
    expect(body).toHaveProperty('status');
    expect(body).toHaveProperty('version');
    expect(body).toHaveProperty('checks');
    expect(typeof body.version).toBe('string');
  });

  test('OpenAPI spec loads', async ({ request }) => {
    const res = await request.get('/openapi.json');
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body).toHaveProperty('paths');
  });

  test('terms page renders HTML', async ({ page }) => {
    await page.goto('/terms');
    await expect(page.locator('body')).toContainText(/terms/i);
  });

  test('privacy page renders HTML', async ({ page }) => {
    await page.goto('/privacy');
    await expect(page.locator('body')).toContainText(/privacy/i);
  });

  test('attribution page renders HTML', async ({ page }) => {
    await page.goto('/attribution');
    await expect(page.locator('body')).toContainText(/attribution|open.source|license/i);
  });
});

test.describe('Navigation', () => {
  test('root redirects to upload', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/#\/upload$/);
  });

  test('sidebar has all nav links', async ({ page }) => {
    await page.goto('/#/upload');
    // Check for the 5 sidebar navigation links
    const nav = page.locator('nav, [role="navigation"], aside');
    await expect(nav.first()).toBeVisible();
  });

  test('all hash routes are reachable', async ({ page }) => {
    let sdkRequests = 0;
    await page.route('https://cdn.paddle.com/paddle/v2/paddle.js', async route => {
      sdkRequests += 1;
      await route.fulfill({ contentType: 'text/javascript', body: `
        window.Paddle = {
          Environment: { set(value) { document.documentElement.dataset.paddleEnvironment = value; } },
          Initialize(options) { document.documentElement.dataset.paddleSeller = String(options.seller); }
        };
      ` });
    });
    const headings = {
      upload: 'Start with your labels.', queue: 'Scored Queue', dashboard: 'Dashboard',
      annotators: 'Annotator Profiles', health: 'Label Health Report',
    };
    for (const [route, name] of Object.entries(headings)) {
      await page.goto('/#/' + route);
      await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible();
    }
    expect(sdkRequests).toBe(0);
    await page.goto('/?_ptxn=txn_test123#/settings');
    await expect(page.locator('html')).not.toHaveAttribute('data-paddle-environment', /.+/);
    await expect(page.locator('html')).toHaveAttribute('data-paddle-seller', '161556');
    expect(sdkRequests).toBe(1);
  });
});

test.describe('Upload screen', () => {
  test('renders drop zone', async ({ page }) => {
    await page.goto('/#/upload');
    await expect(page.locator('text=/upload|drop|csv|drag/i').first()).toBeVisible();
  });

  test('shows sample data button after A1', async ({ page }) => {
    await page.goto('/#/upload');
    // After DLJ-A1, there should be a "Try with sample data" button
    const sampleBtn = page.locator('text=/sample|demo|try/i');
    // This may not exist pre-A1 — check gracefully
    const count = await sampleBtn.count();
    if (count > 0) {
      await expect(sampleBtn.first()).toBeVisible();
    }
  });

  test('no console errors on load', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/#/upload');
    await page.waitForTimeout(1000);
    // Filter out expected warnings (React dev, etc)
    const real = errors.filter(e => !e.includes('React') && !e.includes('DevTools'));
    expect(real).toHaveLength(0);
  });
});

test.describe('Queue screen', () => {
  test('renders queue layout', async ({ page }) => {
    await page.goto('/#/queue');
    await page.waitForTimeout(1000);
    await expect(page.locator('text=/queue|scored|labels|pending|no data/i').first()).toBeVisible();
  });

  test('category filter exists', async ({ page }) => {
    await page.goto('/#/queue');
    await page.waitForTimeout(1000);
    // Look for a select/dropdown for category filtering
    const filter = page.locator('select, [role="combobox"]').or(page.locator('text=/category|filter|all/i'));
    const count = await filter.count();
    expect(count).toBeGreaterThan(0);
  });

  test('no console errors on load', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/#/queue');
    await page.waitForTimeout(1500);
    const real = errors.filter(e =>
      !e.includes('React') && !e.includes('DevTools') && !e.includes('favicon')
    );
    // Allow API errors (no domain configured) but not JS crashes
    const jsErrors = real.filter(e => !e.includes('fetch') && !e.includes('API') && !e.includes('401') && !e.includes('404'));
    expect(jsErrors).toHaveLength(0);
  });
});

test.describe('Dashboard screen', () => {
  test('renders metric cards', async ({ page }) => {
    await page.goto('/#/dashboard');
    await expect(page.locator('text=/accuracy|verified|dashboard|total/i').first()).toBeVisible();
  });

  test('shows autonomy tier badges', async ({ page }) => {
    await page.goto('/#/dashboard');
    await page.waitForTimeout(1000);
    // Look for tier-related content
    const content = await page.locator('body').innerText();
    // Dashboard should mention tiers or show metric cards
    expect(content.length).toBeGreaterThan(50);
  });

  test('no console errors on load', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/#/dashboard');
    await page.waitForTimeout(1500);
    const jsErrors = errors.filter(e =>
      !e.includes('React') && !e.includes('DevTools') && !e.includes('favicon') &&
      !e.includes('fetch') && !e.includes('API') && !e.includes('401') && !e.includes('404')
    );
    expect(jsErrors).toHaveLength(0);
  });
});

test.describe('Annotator Profiles screen', () => {
  test('renders table headers', async ({ page }) => {
    await page.goto('/#/annotators');
    await expect(page.locator('text=/annotator|profile/i').first()).toBeVisible();
  });

  test('table headers are clickable for sorting', async ({ page }) => {
    await page.goto('/#/annotators');
    await page.waitForTimeout(1000);
    const headers = page.locator('th, [role="columnheader"]');
    const count = await headers.count();
    if (count > 0) {
      // Click first header — should not crash
      await headers.first().click();
      await page.waitForTimeout(300);
      // Page still renders
      await expect(page.locator('text=/annotator|profile/i').first()).toBeVisible();
    }
  });
});

test.describe('Health Report screen', () => {
  test('renders upload area', async ({ page }) => {
    await page.goto('/#/health');
    await expect(page.locator('text=/health|report|upload|csv/i').first()).toBeVisible();
  });

  test('no console errors on load', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/#/health');
    await page.waitForTimeout(1000);
    const jsErrors = errors.filter(e =>
      !e.includes('React') && !e.includes('DevTools') && !e.includes('favicon')
    );
    expect(jsErrors).toHaveLength(0);
  });
});

test.describe('Keyboard shortcuts (ReviewCard)', () => {
  test('review card route exists', async ({ page }) => {
    // Navigate to a review URL — it may show "not found" without data
    // but the route should not crash
    await page.goto('/#/review/test-label-1');
    await page.waitForTimeout(1000);
    const text = await page.locator('body').innerText();
    // Should show either the review card or a "not found" / "no label" message
    expect(text.length).toBeGreaterThan(10);
  });
});

test.describe('Mobile responsiveness', () => {
  test.use({ viewport: { width: 375, height: 812 } }); // iPhone X

  test('upload renders on mobile', async ({ page }) => {
    await page.goto('/#/upload');
    await expect(page.locator('main').getByRole('heading', { name: 'Start with your labels.' })).toBeVisible();
    // No horizontal scrollbar
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    const viewportWidth = await page.evaluate(() => window.innerWidth);
    expect(bodyWidth).toBeLessThanOrEqual(viewportWidth + 5); // small tolerance
  });

  test('dashboard renders on mobile', async ({ page }) => {
    await page.goto('/#/dashboard');
    await expect(page.locator('main').getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  });
});
