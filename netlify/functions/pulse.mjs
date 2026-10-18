import { getStore } from '@netlify/blobs';
import { tick } from '../../server/service.mjs';
export default async () => {
  try { await tick(getStore({ name: 'jarvis-paper', consistency: 'strong' })); return new Response(null, { status: 204 }); }
  catch { return new Response(null, { status: 503 }); }
};
export const config = { schedule: '* * * * *' };
