import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { handle } from './api.mjs';
import { tick } from './service.mjs';
if (fs.existsSync('.env')) for (const line of fs.readFileSync('.env', 'utf8').split(/\r?\n/)) { const m = /^\s*([A-Z_][A-Z_0-9]*)\s*=\s*(.*?)\s*$/.exec(line); if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^['"]|['"]$/g, ''); }
fs.mkdirSync('.local', { recursive: true }); const statePath = path.resolve('.local/paper.json');
const store = {
  async getWithMetadata() { if (!fs.existsSync(statePath)) return null; const raw = fs.readFileSync(statePath, 'utf8'); return { data: JSON.parse(raw), etag: createHash('sha256').update(raw).digest('hex') }; },
  async setJSON(key, data, options) {
    // Synchronous read/check/rename section is atomic with respect to this single Node process.
    const raw = fs.existsSync(statePath) ? fs.readFileSync(statePath, 'utf8') : null;
    if (options.onlyIfNew && raw !== null || options.onlyIfMatch && (!raw || createHash('sha256').update(raw).digest('hex') !== options.onlyIfMatch)) return { modified: false };
    fs.writeFileSync(statePath + '.tmp', JSON.stringify(data)); fs.renameSync(statePath + '.tmp', statePath); return { modified: true };
  },
};
const assets = new Map([['/', ['index.html', 'text/html']], ['/index.html', ['index.html', 'text/html']], ['/app.js', ['app.js', 'text/javascript']], ['/style.css', ['style.css', 'text/css']]]);
const port = Number(process.env.PORT || 3000);
const server = http.createServer(async (req, res) => {
  try {
    const pathname = new URL(req.url, `http://127.0.0.1:${port}`).pathname;
    if (pathname === '/api/agent') {
      let body = ''; for await (const chunk of req) { body += chunk; if (body.length > 2048) { res.writeHead(413).end(); return; } }
      const request = new Request(`http://127.0.0.1:${port}/api/agent`, { method: req.method, headers: req.headers, ...(!['GET', 'HEAD'].includes(req.method) ? { body } : {}) });
      const response = await handle(request, store); res.writeHead(response.status, Object.fromEntries(response.headers)); res.end(await response.text()); return;
    }
    const asset = assets.get(pathname); if (!asset) { res.writeHead(404).end('Not found'); return; }
    res.writeHead(200, { 'Content-Type': `${asset[1]}; charset=utf-8`, 'X-Content-Type-Options': 'nosniff' }); res.end(fs.readFileSync(path.resolve('web', asset[0])));
  } catch { res.writeHead(500).end('Local server error'); }
});
server.listen(port, '127.0.0.1', () => console.log(`JARVIS running locally on port ${port}. No wallet or real-money trades.`));
const timer = setInterval(() => tick(store).catch(() => {}), 60000);
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { clearInterval(timer); server.close(() => process.exit(0)); });
