// Test-only static server. No production API, database, model, or credentials.
import { createServer } from 'node:http';
import { readFile, readdir } from 'node:fs/promises';
import { resolve, extname } from 'node:path';

const root = resolve(import.meta.dirname, '../..');
const assets = new Map([
  ['/', ['counter/entrypoints/static/index.html', 'text/html']],
  ['/static/app.js', ['counter/entrypoints/static/app.js', 'text/javascript']],
  ['/static/styles.css', ['counter/entrypoints/static/styles.css', 'text/css']],
]);
for (const name of await readdir(resolve(root, 'resources/images'))) {
  if (!/\.(png|jpe?g)$/i.test(name)) continue;
  assets.set(`/api/samples/${name}`, [`resources/images/${name}`, extname(name) === '.png' ? 'image/png' : 'image/jpeg']);
}
const server = createServer(async (request, response) => {
  const asset = assets.get(new URL(request.url, 'http://localhost').pathname);
  if (!asset || request.method !== 'GET') { response.writeHead(404).end(); return; }
  try {
    const body = await readFile(resolve(root, asset[0]));
    response.writeHead(200, {
      'Content-Type': asset[1], 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
      'Content-Security-Policy': "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
    });
    response.end(body);
  } catch { response.writeHead(500).end(); }
});
server.listen(5197, '127.0.0.1');
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close(() => process.exit()));
