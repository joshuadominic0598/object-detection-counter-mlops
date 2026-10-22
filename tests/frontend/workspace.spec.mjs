import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { test, expect, openApp, sample, run, verifyCloud } from './fixtures.mjs';

const carlot = resolve(import.meta.dirname, '../../resources/images/carlot.jpeg');
async function uploads(page, number) {
  if(number > 1) await page.locator('#batch-mode').check();
  const buffer = await readFile(carlot);
  await page.locator('#file-input').setInputFiles(Array.from({ length: number }, (_, index) => ({
    name: `batch-${index + 1}.jpg`, mimeType: 'image/jpeg', buffer,
  })));
  await expect(page.locator('.queue-item')).toHaveCount(Math.min(number, 20));
}

test('starts connected, lists samples, and defaults Roboflow to the verified hosted model', async ({ page, app }) => {
  await openApp(page);
  await expect(page.locator('#local-tab')).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#run-button')).toBeDisabled();
  await page.locator('#roboflow-tab').click();
  await expect(page.locator('#roboflow-mode')).toHaveValue('model');
  await expect(page.locator('#model-id')).toHaveValue('parking-detection-ewm7h/3');
  await expect(page.locator('#model-field')).toBeVisible();
  await expect(page.locator('#workflow-fields')).toBeHidden();
  await expect(page.locator('#api-key')).toHaveValue('');
  await expect(page.locator('#key-hint')).toContainText('Leave blank');
  await expect(page.locator('#cloud-status')).not.toHaveClass(/connected/);
  await expect(page.locator('.cloud-note')).toContainText('trained classes');
  expect(app.calls).toHaveLength(0);
});

test('runs local inference with the selected threshold and displays metrics and a download', async ({ page, app }) => {
  await openApp(page);
  await page.locator('#threshold').press('ArrowRight');
  await expect(page.locator('#threshold-value')).toHaveText('51%');
  await sample(page);
  await run(page);
  expect(app.calls[0]).toMatchObject({ provider: 'local', threshold: '0.51', counter: 'true', file_name: 'carlot.jpeg' });
  expect(app.calls[0].file_size).toBeGreaterThan(0);
  await expect(page.locator('#metric-objects')).toHaveText('2');
  await expect(page.locator('#metric-classes')).toHaveText('2');
  await expect(page.locator('#metric-confidence')).toHaveText('87.5%');
  await expect(page.locator('#metric-latency')).toHaveText('123 ms');
  await expect(page.locator('#image-counts')).toContainText('car');
  await expect(page.locator('#persistent-total')).toHaveText('2');
  const download = page.waitForEvent('download');
  await page.locator('#download-result').click();
  expect((await download).suggestedFilename()).toBe('carlot.jpeg');
});

test('focuses detections with pointer or touch and supports keyboard inspection', async ({ page, app }, testInfo) => {
  await openApp(page); await sample(page); await run(page);
  const box = page.locator('#boxes .bbox').first();
  if (testInfo.project.name === 'mobile') await box.tap(); else await box.hover();
  await expect(page.locator('#boxes .focus-shade')).toHaveAttribute('visibility', 'visible');
  await expect(page.locator('#boxes .focus-shade')).toHaveCSS('fill-opacity', '0.66');
  await expect(page.locator('#boxes .box-label')).toHaveText('car  95.0%');
  await expect(box).toHaveAttribute('stroke-width', '3');
  await expect(page.locator('#boxes .bbox').nth(1)).toHaveCSS('opacity', '0.2');
  await box.focus(); await box.press('Enter');
  await expect(page.locator('#boxes .box-label')).toHaveAttribute('visibility', 'visible');
  await box.press('Escape');
  await expect(page.locator('#boxes .focus-shade')).toHaveAttribute('visibility', 'hidden');
});

test('uploads and processes a sequential batch, then inspects prior results', async ({ page, app }) => {
  let active = 0, peak = 0;
  app.gate = async () => { active++; peak = Math.max(active, peak); await new Promise(resolve => setTimeout(resolve, 30)); active--; };
  await openApp(page); await uploads(page, 3); await run(page);
  expect(app.calls.map(item => item.file_name)).toEqual(['batch-1.jpg', 'batch-2.jpg', 'batch-3.jpg']);
  expect(peak).toBe(1);
  await expect(page.locator('#batch-metrics')).toContainText('3 succeeded · 0 failed · 6 detections');
  await expect(page.locator('#persistent-total')).toHaveText('6');
  await page.getByRole('button', { name: 'View batch-1.jpg', exact: true }).click();
  await expect(page.locator('#image-caption')).toContainText('batch-1.jpg');
  expect(app.calls).toHaveLength(3);
  await page.locator('#clear-queue').click();
  await expect(page.locator('.queue-item')).toHaveCount(0);
  await expect(page.locator('#persistent-total')).toHaveText('6');
});

test('keeps successful batch results and counts when one image fails', async ({ page, app }) => {
  app.failIndices.add(1);
  await openApp(page); await uploads(page, 3); await run(page);
  expect(app.calls).toHaveLength(3);
  await expect(page.locator('#batch-metrics')).toContainText('2 succeeded · 1 failed · 4 detections');
  await expect(page.locator('#persistent-total')).toHaveText('4');
  await page.getByRole('button', { name: 'View batch-2.jpg', exact: true }).click();
  await expect(page.locator('#notice')).toContainText('Roboflow denied access');
  await expect(page.locator('#download-result')).toBeHidden();
  await page.getByRole('button', { name: 'View batch-1.jpg', exact: true }).click();
  await expect(page.locator('#metric-objects')).toHaveText('2');
});

test('stops after the in-flight image and resumes without resubmitting completed images', async ({ page, app }) => {
  let release;
  const held = new Promise(resolve => { release = resolve; });
  app.gate = index => index === 0 ? held : Promise.resolve();
  await openApp(page); await uploads(page, 3);
  await page.locator('#run-button').click();
  await expect.poll(() => app.calls.length).toBe(1);
  await page.locator('#stop-button').click();
  release();
  await expect(page.locator('#run-progress')).toContainText('Stopped · 1 processed');
  await expect(page.locator('#persistent-total')).toHaveText('2');
  expect(app.calls).toHaveLength(1);
  await run(page);
  expect(app.calls.map(item => item.file_name)).toEqual(['batch-1.jpg', 'batch-2.jpg', 'batch-3.jpg']);
  await expect(page.locator('#persistent-total')).toHaveText('6');
});

test('preview-only inference does not increment totals and sessions survive reload', async ({ page, app }) => {
  await openApp(page); await sample(page); await run(page);
  const originalSession = await page.locator('#session-id').inputValue();
  await page.reload();
  await expect(page.locator('#session-id')).toHaveValue(originalSession);
  await expect(page.locator('#persistent-total')).toHaveText('2');
  await page.locator('#persist-counts').uncheck();
  await sample(page); await run(page);
  expect(app.calls[1].counter).toBe('false');
  await expect(page.locator('#persistent-total')).toHaveText('2');
  await page.locator('#new-session').click();
  await expect(page.locator('#persistent-total')).toHaveText('0');
  expect(await page.locator('#session-id').inputValue()).not.toBe(originalSession);
  await page.locator('#session-id').fill(originalSession);
  await page.locator('#load-session').click();
  await expect(page.locator('#persistent-total')).toHaveText('2');
});

test('routes hosted-model and workflow requests explicitly and keeps keys out of storage', async ({ page, app }) => {
  app.serverKey = false;
  await openApp(page); await page.locator('#roboflow-tab').click(); await sample(page);
  await expect(page.locator('#run-button')).toBeDisabled();
  await page.locator('#test-connection').click();
  await expect(page.locator('#notice')).toContainText('Enter your Roboflow API key');
  expect(app.calls).toHaveLength(0);
  await page.locator('#api-key').fill('synthetic-test-key');
  await verifyCloud(page); await run(page);
  expect(app.calls[0]).toMatchObject({ provider: 'roboflow', roboflow_mode: 'model', model_id: 'parking-detection-ewm7h/3', api_key: 'synthetic-test-key' });
  await expect(page.locator('#cloud-status')).toHaveClass(/connected/);
  await page.locator('#roboflow-mode').selectOption('workflow');
  await expect(page.locator('#workflow-fields')).toBeVisible();
  await expect(page.locator('#model-field')).toBeHidden();
  await expect(page.locator('#cloud-status')).not.toHaveClass(/connected/);
  await page.locator('#output-path').fill('detections.cars');
  await expect(page.locator('#run-button')).toBeDisabled();
  await verifyCloud(page); await sample(page); await run(page);
  expect(app.connections).toHaveLength(2);
  expect(app.connections[1]).toMatchObject({roboflow_mode: 'workflow', output_path: 'detections.cars'});
  expect(app.calls[1]).toMatchObject({ roboflow_mode: 'workflow', workspace_name: 'model-version2', workflow_id: 'parking-detection-v3-logic', output_path: 'detections.cars' });
  const storage = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  expect(storage).not.toContain('synthetic-test-key');
  await page.reload(); await page.locator('#roboflow-tab').click();
  await expect(page.locator('#api-key')).toHaveValue('');
  await expect(page.locator('#roboflow-mode')).toHaveValue('model');
});

test('keeps provider sessions separate and resumes their respective counts', async ({ page, app }) => {
  await openApp(page); await sample(page); await run(page);
  const local = await page.locator('#session-id').inputValue();
  await page.locator('#roboflow-tab').click();
  const cloud = await page.locator('#session-id').inputValue();
  expect(cloud).not.toBe(local);
  await expect(page.locator('#persistent-total')).toHaveText('0');
  await verifyCloud(page); await sample(page); await run(page);
  expect(app.calls[1]).toMatchObject({ session_id: cloud, roboflow_mode: 'model', api_key: '' });
  await page.locator('#local-tab').click();
  await expect(page.locator('#session-id')).toHaveValue(local);
  await expect(page.locator('#persistent-total')).toHaveText('2');
});

test('rejects invalid, malformed and oversized files before sending inference', async ({ page, app }) => {
  await openApp(page);
  for (const file of [
    { name: 'bad.gif', mimeType: 'image/gif', buffer: Buffer.from('GIF89a') },
    { name: 'broken.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('not an image') },
    { name: 'too-large.jpg', mimeType: 'image/jpeg', buffer: Buffer.alloc(10 * 1024 * 1024 + 1) },
  ]) {
    await page.locator('#file-input').setInputFiles(file);
    await expect(page.locator('#notice')).toContainText(file.name);
    await expect(page.locator('.queue-item')).toHaveCount(0);
  }
  expect(app.calls).toHaveLength(0);
  await expect(page.locator('#run-button')).toBeDisabled();
});

test('caps the queue at twenty images and rejects unsafe session IDs', async ({ page, app }) => {
  await openApp(page); await uploads(page, 21);
  await expect(page.locator('#notice')).toContainText('Batch limit reached');
  await expect(page.locator('#queue-count')).toHaveText('20 / 20');
  await page.locator('#session-id').fill('../../private');
  await page.locator('#run-button').click();
  await expect(page.locator('#notice')).toContainText('Session ID must contain');
  expect(app.calls).toHaveLength(0);
});

test('renders external class labels as text and fits the viewport after detection', async ({ page, app }) => {
  app.label = '<img src=x onerror="window.injected=true">';
  await openApp(page); await sample(page); await run(page);
  await expect(page.locator('#image-counts')).toContainText(app.label);
  await expect(page.locator('#image-counts img')).toHaveCount(0);
  await expect(page.locator('#persistent-classes img')).toHaveCount(0);
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
  const dimensions = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth }));
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport);
  const canvas = await page.locator('.viewer-panel').boundingBox();
  expect(canvas.x).toBeGreaterThanOrEqual(0);
  expect(canvas.x + canvas.width).toBeLessThanOrEqual(dimensions.viewport);
});

test('opens monitoring and sessions in separate tabs and disables runs while offline', async ({ page, app }) => {
  await openApp(page);
  await page.context().route('**/dashboards/*.html', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><title>Test report</title><h1>Test dashboard</h1>',
  }));
  for (const [label, file] of [['Monitoring', 'monitoring_dashboard.html'], ['Sessions', 'session_dashboard.html']]) {
    // On mobile the visible labels collapse to icons; the destinations remain the same.
    const link = page.locator(`a[href="/dashboards/${file}"]`);
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', 'noopener');
    const opening = page.waitForEvent('popup');
    await link.click();
    const popup = await opening;
    await expect(popup).toHaveURL(`http://127.0.0.1:5197/dashboards/${file}`);
    await expect(popup.getByRole('heading', { name: 'Test dashboard' })).toBeVisible();
    await popup.close();
  }
  app.online = false;
  await page.reload();
  await expect(page.locator('#api-status')).toHaveText('API offline');
  await page.getByRole('button', { name: 'Use sample carlot', exact: true }).click();
  await expect(page.locator('.queue-item')).toHaveCount(1);
  await expect(page.locator('#run-button')).toBeDisabled();
  expect(app.calls).toHaveLength(0);
});


test('single-image mode replaces selections and keeps persistent counts across runs', async ({ page, app }) => {
  await openApp(page);
  await expect(page.getByRole('radio', {name: 'Single image', exact: true})).toBeChecked();
  await expect(page.getByRole('radio', {name: 'Batch', exact: true})).not.toBeChecked();
  await expect(page.locator('#file-input')).not.toHaveAttribute('multiple');
  await expect(page.locator('#queue-panel')).toBeHidden();
  await sample(page, 'carlot'); await sample(page, 'carpark3');
  await expect(page.locator('.queue-item')).toHaveCount(1);
  await expect(page.locator('#queue-count')).toHaveText('1 / 1');
  await expect(page.locator('#image-caption')).toContainText('carpark3.png');
  await run(page);
  expect(app.calls.map(item => item.file_name)).toEqual(['carpark3.png']);
  await sample(page, 'carlot'); await run(page);
  expect(app.calls.map(item => item.file_name)).toEqual(['carpark3.png', 'carlot.jpeg']);
  await expect(page.locator('#persistent-total')).toHaveText('4');
  await expect(page.locator('.queue-item')).toHaveCount(1);
});

test('batch mode explicitly adds samples and switching back keeps only the selected image', async ({ page, app }) => {
  await openApp(page); await page.locator('#batch-mode').check();
  await expect(page.locator('#file-input')).toHaveAttribute('multiple', '');
  await expect(page.locator('#queue-panel')).toBeVisible();
  await expect(page.locator('#upload-heading')).toHaveText('Add images to your batch');
  await sample(page, 'carlot'); await sample(page, 'carpark3');
  await expect(page.locator('.queue-item')).toHaveCount(2);
  await expect(page.locator('#run-label')).toHaveText('Run batch');
  await page.locator('#single-mode').check();
  await expect(page.locator('.queue-item')).toHaveCount(1);
  await expect(page.locator('#queue-panel')).toBeHidden();
  await expect(page.locator('#image-caption')).toContainText('carpark3.png');
  await run(page);
  expect(app.calls.map(item => item.file_name)).toEqual(['carpark3.png']);
});

test('connection checking gates cloud runs and edits require another verification', async ({ page, app }) => {
  await openApp(page); await page.locator('#roboflow-tab').click(); await sample(page);
  await expect(page.locator('#run-button')).toBeDisabled();
  await verifyCloud(page);
  expect(app.calls).toHaveLength(0);
  expect(app.connections[0]).toMatchObject({roboflow_mode: 'model', model_id: 'parking-detection-ewm7h/3', api_key: ''});
  await expect(page.locator('#persistent-total')).toHaveText('0');
  await expect(page.locator('#run-button')).toBeEnabled();
  await page.locator('#model-id').fill('another-model/2');
  await expect(page.locator('#cloud-status')).not.toHaveClass(/connected/);
  await expect(page.locator('#run-button')).toBeDisabled();
  await verifyCloud(page); await run(page);
  expect(app.calls[0].model_id).toBe('another-model/2');
  await page.locator('#api-key').fill('changed-key');
  await expect(page.locator('#cloud-status')).not.toHaveClass(/connected/);
  await expect(page.locator('#run-button')).toBeDisabled();
  await page.reload(); await page.locator('#roboflow-tab').click();
  await expect(page.locator('#cloud-status')).not.toHaveClass(/connected/);
});

test('failed connection stays blocked and checking locks configuration and uploads', async ({ page, app }) => {
  app.connectionFails = true;
  await openApp(page); await page.locator('#roboflow-tab').click(); await sample(page);
  await page.locator('#test-connection').click();
  await expect(page.locator('#cloud-status')).toContainText('Connection failed');
  await expect(page.locator('#notice')).toContainText('Roboflow denied access');
  await expect(page.locator('#run-button')).toBeDisabled();
  expect(app.calls).toHaveLength(0);
  app.connectionFails = false;
  let release; app.connectionGate = () => new Promise(resolve => {release = resolve;});
  await page.locator('#test-connection').click();
  await expect.poll(() => app.connections.length).toBe(2);
  await expect(page.locator('#model-id')).toBeDisabled();
  await expect(page.locator('#api-key')).toBeDisabled();
  await expect(page.locator('#batch-mode')).toBeDisabled();
  await expect(page.locator('#dropzone')).toBeDisabled();
  await expect(page.locator('#test-connection')).toHaveText('Testing…');
  release();
  await expect(page.locator('#cloud-status')).toHaveClass(/connected/);
  await expect(page.locator('#run-button')).toBeEnabled();
});
