import test from 'node:test';
import assert from 'node:assert/strict';
import { samplesFor, nearestIndex } from '../web/chart.js';
test('chart uses observed values only and preserves price source', () => {
  const rows = [
    { at: '2026-10-18T12:02:00Z', ethUsd: 3002, ethSource: 'DEX fixture' },
    { at: '2026-10-18T12:00:00Z', ethUsd: 3000 },
    { at: 'invalid', ethUsd: 4000 },
    { at: '2026-10-18T12:01:00Z', ethUsd: null },
  ];
  const p = samplesFor(rows, 'ethUsd'); assert.equal(p.length, 2); assert.equal(p[0].value, 3000); assert.equal(p[1].ethSource, 'DEX fixture'); assert.equal(p[1].timestamp - p[0].timestamp, 120000);
});
test('hover selects nearest actual time across irregular collection gaps', () => {
  const p = [0, 60000, 600000].map(timestamp => ({ timestamp }));
  assert.equal(nearestIndex(p, 120000), 1); assert.equal(nearestIndex(p, 590000), 2); assert.equal(nearestIndex(p, -1), 0); assert.equal(nearestIndex(p, 900000), 2); assert.equal(nearestIndex([], 1), -1);
});
