import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { controlled, uploadWalls, evidence } from './capture-fixture';

async function savedDimensions(page: Page, small = false) {
  for (const [label, value] of [['Overall width', small ? '1.4' : '6'], ['Overall depth', small ? '1.4' : '5'], ['Notch width', small ? '.6' : '2'], ['Notch depth', small ? '.6' : '2'], ['Ceiling height', '2.7']]) await page.getByLabel(label!, { exact: true }).fill(value!);
  await expect(page.getByRole('checkbox', { name: /I checked and confirm all five/ })).toBeDisabled();
  await page.getByRole('button', { name: 'Save Room details', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: /I checked and confirm all five/ })).toBeEnabled();
}
async function review(page: Page) {
  for (const wall of 'ABCDEF') await page.getByRole('checkbox', { name: `I reviewed every Opening on Wall ${wall}, including if there are none.`, exact: true }).check();
  await page.getByRole('checkbox', { name: /I checked and confirm all five/ }).check();
  await page.getByRole('checkbox', { name: 'I acknowledge the empty-Room assumption.', exact: true }).check();
  await page.getByRole('button', { name: 'Review and confirm Room', exact: true }).click();
  await expect(page.getByText('Room confirmed. Choose a Style image to generate.')).toBeVisible();
}
async function shot(page: Page, name: string) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  mkdirSync(evidence, { recursive: true });
  await page.screenshot({ path: join(evidence, `ticket-10-${name}.png`) });
}
for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) test(`controlled L Capture: six photos, correction, real solver/Mesh, no-fit and retry ${viewport.width}`, async ({ page, request }) => {
  await page.setViewportSize(viewport);
  const flow = await controlled(page, request);
  await page.getByRole('radio', { name: 'Bedroom', exact: true }).check();
  await page.getByRole('radio', { name: 'L-shaped', exact: true }).check();
  await uploadWalls(page, ['A', 'B', 'C', 'D', 'E', 'F']);
  await savedDimensions(page);
  expect(flow.capture.draft.dimensionsConfirmed).toBe(false);
  expect(flow.capture.draft.wallReviews).toEqual([]);
  await page.getByLabel('Notch width', { exact: true }).fill('6');
  await expect(page.getByLabel('Notch width', { exact: true })).toHaveAttribute('aria-invalid', 'true');
  await expect(page.getByRole('button', { name: 'Review and confirm Room', exact: true })).toBeDisabled();
  await page.getByLabel('Notch width', { exact: true }).scrollIntoViewIfNeeded();
  await shot(page, `invalid-notch-${viewport.width}`);
  await page.getByLabel('Notch width', { exact: true }).fill('2');
  // Restoring the exact saved value needs no hidden save or re-confirmation.
  await page.getByRole('button', { name: 'Add missed Opening', exact: true }).click();
  await page.getByLabel('Opening 1 wall', { exact: true }).selectOption('wall-notch-vertical');
  await page.getByLabel('Opening 1 type', { exact: true }).selectOption('door');
  for (const [label, value] of [['Distance from wall start', '.2'], ['Width', '.7'], ['Bottom / sill height', '0'], ['Height', '2'], ['Inward clearance', '0']]) await page.getByLabel(`Opening 1 ${label}`, { exact: true }).fill(value!);
  await page.getByLabel('Opening 1 door direction', { exact: true }).selectOption('inward');
  await page.getByLabel('Opening 1 swing angle', { exact: true }).selectOption('90');
  await page.getByLabel('Opening 1 hinge side', { exact: true }).selectOption('end');
  await page.getByRole('checkbox', { name: 'I reviewed this Opening and its operation.', exact: true }).check();
  await review(page);
  expect(flow.capture.room.walls.map((w: any) => w.id)).toEqual(['wall-north', 'wall-notch-vertical', 'wall-notch-horizontal', 'wall-east', 'wall-south', 'wall-west']);
  expect(flow.capture.room.openings[0].offsetAlongWallM).toBeCloseTo(-.45);
  await page.getByTestId('capture-room-diagram').scrollIntoViewIfNeeded();
  await expect(page.getByRole('list', { name: 'Derived wall lengths' })).toContainText('Wall F: 5 m');
  await shot(page, `six-wall-directions-${viewport.width}`);
  await page.getByRole('radio', { name: /Soft neutrals and warm wood/ }).check();
  await page.getByRole('button', { name: 'Generate confirmed Room', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Validated furnished Room', exact: true })).toBeVisible();
  await page.getByTestId('room-canvas').scrollIntoViewIfNeeded();
  await page.waitForFunction(() => Object.values(window.__furnitureos?.instances ?? {}).some((p: any) => p.actualFrameRendered && p.renderedMeshCount > 0 && p.screenVisible));
  await shot(page, `solved-l-${viewport.width}`);
  writeFileSync(join(evidence, `ticket-10-scene-${viewport.width}.json`), JSON.stringify({ controlled: true, room: flow.capture.room, facts: await page.evaluate(() => window.__furnitureos) }, null, 2));
  // Height is a metric change too: the saved normalized draft revokes every review.
  await page.getByLabel('Ceiling height', { exact: true }).fill('2.8');
  await page.getByRole('button', { name: 'Save Room details', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: /I checked and confirm all five/ })).not.toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'I reviewed every Opening on Wall B, including if there are none.', exact: true })).not.toBeChecked();
  await expect(page.getByRole('heading', { name: 'Validated furnished Room', exact: true })).toHaveCount(0);
  // Small valid L: authoritative no-fit, then visible correction and explicit retry.
  await page.getByRole('button', { name: 'Remove false Opening', exact: true }).click();
  await savedDimensions(page, true);
  await review(page);
  await page.getByRole('button', { name: 'Generate confirmed Room', exact: true }).click();
  await expect(page.getByTestId('capture-limiting-constraint')).toContainText('Limiting constraint:');
  await expect(page.getByRole('button', { name: 'Retry generation explicitly', exact: true })).toBeVisible();
  await page.getByTestId('capture-limiting-constraint').scrollIntoViewIfNeeded();
  await shot(page, `no-fit-${viewport.width}`);
  await page.getByRole('button', { name: 'Review dimensions and Openings', exact: true }).click();
  await savedDimensions(page);
  await review(page);
  await page.getByRole('button', { name: 'Generate confirmed Room', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Validated furnished Room', exact: true })).toBeVisible();
  // A topology transition keeps all photo slots and marks inactive primary IDs.
  await page.getByRole('radio', { name: 'Rectangle', exact: true }).check();
  await page.getByRole('button', { name: 'Save Room details', exact: true }).click();
  await expect(page.locator('.photo-list li')).toHaveCount(6);
  await expect(page.getByText('This primary wall is inactive.', { exact: false })).toHaveCount(2);
  expect(flow.capture.photos.filter((p: any) => p.primaryWallId.startsWith('wall-notch')).length).toBe(2);
});
