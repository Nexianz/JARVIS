import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { getStore } from '@netlify/blobs';
import { BlobsServer } from '@netlify/blobs/server';
import { command, load, tick, publicState } from '../server/service.mjs';
test('Netlify SDK + local Blobs server persist state, enforce conditional writes and reload without browser storage', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'jarvis-blobs-'));
  const server = new BlobsServer({ directory, token: 'synthetic-storage-token', logger: () => {} });
  try {
    const address = await server.start();
    const opts = { name: 'jarvis-paper-test', siteID: 'synthetic-site', token: 'synthetic-storage-token', apiURL: `http://127.0.0.1:${address.port}`, consistency: 'strong' };
    const store = getStore(opts);
    const env = { PAPER_ADMIN_TOKEN: 'synthetic-owner-password', ALCHEMY_API_KEY: 'synthetic' };
    // v11's local emulator omits ETag on GET. Verify SDK conditions using write-returned ETags;
    // service-level read/CAS semantics are exercised separately with a versioned store.
    const first = await store.setJSON('paper-agent-v1', { balance: 5000, running: true }, { onlyIfNew: true });
    assert.equal(first.modified, true); assert.ok(first.etag);
    const duplicate = await store.setJSON('paper-agent-v1', { balance: 1 }, { onlyIfNew: true }); assert.equal(duplicate.modified, false);
    const reopened = getStore(opts); const initial = await reopened.getWithMetadata('paper-agent-v1', { type: 'json' }); assert.equal(initial.data.balance, 5000);
    const second = await store.setJSON('paper-agent-v1', { balance: 4990, running: false }, { onlyIfMatch: first.etag }); assert.equal(second.modified, true);
    const stale = await store.setJSON('paper-agent-v1', { balance: 9999 }, { onlyIfMatch: first.etag }); assert.equal(stale.modified, false);
    assert.equal((await reopened.get('paper-agent-v1', { type: 'json' })).balance, 4990);
  } finally { await server.stop(); await fs.rm(directory, { recursive: true, force: true }); }
});
