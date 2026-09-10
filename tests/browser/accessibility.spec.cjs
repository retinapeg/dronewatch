const { test, expect } = require('@playwright/test');
const AxeBuilder = require('@axe-core/playwright').default;

test('operator view has no automatic WCAG A or AA violations', async ({ page }, testInfo) => {
  test.skip(!['android-360', 'desktop'].includes(testInfo.project.name), 'Check the smallest phone and desktop accessibility trees.');
  await page.goto('/');
  await page.getByRole('button', { name: 'Pause scenario', exact: true }).click();
  const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  await testInfo.attach('accessibility-results', { body: JSON.stringify(result, null, 2), contentType: 'application/json' });
  expect(result.violations.map(v => ({ id: v.id, impact: v.impact, description: v.description, nodes: v.nodes.map(n => ({ target: n.target, summary: n.failureSummary })) }))).toEqual([]);
});

test('keyboard selection survives scenario updates and focus remains usable', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Keyboard regression is independent of touch viewport.');
  await page.goto('/');
  const target = page.getByRole('button', { name: 'Select target DW-03', exact: true });
  await target.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('target-detail')).toContainText('DW-03');
  await page.waitForTimeout(1500);
  await expect(target).toBeFocused();
  await page.keyboard.press('Tab');
  expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe('BODY');
});
