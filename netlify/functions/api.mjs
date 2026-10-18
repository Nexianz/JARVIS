import { getStore } from '@netlify/blobs';
import { handle } from '../../server/api.mjs';
export default async request => {
  try { return await handle(request, getStore({ name: 'jarvis-paper', consistency: 'strong' })); }
  catch { return Response.json({ error: 'Varig lagring er ikke tilgjengelig. Kontroller Netlify Blobs.' }, { status: 503 }); }
};
export const config = { path: '/api/agent' };
