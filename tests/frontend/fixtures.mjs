import { test as base, expect } from '@playwright/test';

export const test = base.extend({
  app: async ({ page, context }, use) => {
    const api = {
      calls: [], totals: new Map(), serverKey: true, online: true,
      failIndices: new Set(), gate: null, label: 'car', connections: [], connectionFails: false, connectionGate: null,
    };
    // Accidental external requests fail rather than reaching a paid provider.
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin === 'http://127.0.0.1:5197') return route.continue();
      return route.abort();
    });
    await page.route('**/api/**', async route => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      const json = (body, status = 200) => route.fulfill({ status, json: body });
      if (pathname === '/api/status') return json(api.online ? {
        status: 'ok', local_model: 'test-local.pt', server_key_available: api.serverKey,
      } : { detail: 'API unavailable' }, api.online ? 200 : 503);
      if (pathname === '/api/samples') return json(['car.png', 'car2.png', 'cardetect.png', 'carlot.jpeg', 'carpark.jpeg', 'carpark2.jpeg', 'carpark3.png', 'carpark4.png'].map(id => ({ id, name: id.split('.')[0], url: `/api/samples/${id}` })));
      if (pathname.startsWith('/api/samples/')) return route.continue();
      if (pathname.startsWith('/api/sessions/')) {
        const session_id = decodeURIComponent(pathname.split('/').pop());
        return json({ session_id, total_counts: api.totals.get(session_id) || {} });
      }
      if (pathname === '/api/roboflow/test-connection') {
        const form = await new Request('http://test.local', {method: 'POST', headers: request.headers(), body: request.postDataBuffer()}).formData();
        const fields = Object.fromEntries(form); api.connections.push(fields);
        if (api.connectionGate) await api.connectionGate();
        if (api.connectionFails) return json({detail: 'Roboflow denied access. Check your key and deployment permissions.'}, 502);
        return json({status: 'connected', mode: fields.roboflow_mode, latency_ms: 42});
      }
      if (pathname !== '/api/detect') return json({ detail: 'Unexpected test API route' }, 404);
      const data = await new Request('http://test.local', {
        method: 'POST', headers: request.headers(), body: request.postDataBuffer(),
      }).formData();
      const fields = Object.fromEntries([...data].filter(([key]) => key !== 'file'));
      fields.file_name = data.get('file').name;
      fields.file_size = data.get('file').size;
      const index = api.calls.push(fields) - 1;
      if (api.gate) await api.gate(index);
      if (api.failIndices.has(index)) return json({ detail: 'Roboflow denied access. Check your key and deployment permissions.' }, 502);
      const counts = { [api.label]: 1, free: 1 };
      const totals = { ...(api.totals.get(fields.session_id) || {}) };
      if (fields.counter === 'true') {
        for (const [label, number] of Object.entries(counts)) totals[label] = (totals[label] || 0) + number;
        api.totals.set(fields.session_id, totals);
      }
      return json({
        request_id: `test-${index}`, session_id: fields.session_id, provider: fields.provider,
        image_name: fields.file_name, width: 524, height: 349,
        predictions: [
          { class_name: api.label, score: .95, box: { xmin: 30, ymin: 100, xmax: 160, ymax: 260 } },
          { class_name: 'free', score: .8, box: { xmin: 220, ymin: 100, xmax: 350, ymax: 260 } },
        ],
        counts, total_counts: totals, detection_count: 2, class_count: 2,
        mean_confidence: .875, latency_ms: 123, counter: fields.counter === 'true',
        image_url: '/api/samples/carlot.jpeg', annotated_url: '/api/samples/carlot.jpeg',
      });
    });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await use(api);
    expect(errors, 'no uncaught browser JavaScript errors').toEqual([]);
  },
});
export { expect };
export async function openApp(page) {
  await page.goto('/');
  await expect(page.locator('#api-status')).toHaveText('API connected');
  await expect(page.locator('#samples button')).toHaveCount(8);
}
export async function sample(page, name = 'carlot') {
  await page.getByRole('button', { name: `Use sample ${name}`, exact: true }).click();
  await expect(page.locator('#run-count')).not.toHaveText('0');
}
export async function run(page) {
  await page.locator('#run-button').click();
  await expect(page.locator('#run-progress')).toContainText(/Batch complete|Detection complete/);
}

export async function verifyCloud(page) {
  await page.locator('#test-connection').click();
  await expect(page.locator('#cloud-status')).toHaveClass(/connected/);
}
