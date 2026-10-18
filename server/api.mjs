import { authorized, command, publicState, tick } from './service.mjs';
function json(value, status = 200) { return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' } }); }
export async function handle(request, store, options = {}) {
  const env = options.env ?? process.env;
  try {
    if (request.method === 'GET') return json(await publicState(store, env));
    if (request.method !== 'POST') return json({ error: 'Kun GET/POST.' }, 405);
    if (!authorized(request, env)) return json({ error: 'Eierpassord mangler eller er feil. PAPER_ADMIN_TOKEN må ha minst 16 tegn.' }, 401);
    const origin = request.headers.get('origin'); if (origin && origin !== new URL(request.url).origin) return json({ error: 'Ugyldig opprinnelse.' }, 403);
    const text = await request.text(); if (text.length > 1024) return json({ error: 'For stor forespørsel.' }, 413);
    let body; try { body = JSON.parse(text); } catch { return json({ error: 'Ugyldig JSON.' }, 400); }
    if (body.action === 'scan') {
      const result = await tick(store, { ...options, manual: true });
      return json({ ...result, state: await publicState(store, env) });
    }
    const result = await command(store, body.action, body.channel, { ...options, env });
    if (result.conflict) return json({ error: 'Agenten jobber nå. Prøv igjen om litt.' }, 409);
    return json({ state: await publicState(store, env) });
  } catch {
    return json({ error: 'Forespørselen kunne ikke fullføres. Kontroller Netlify-innstillinger eller prøv igjen.' }, 500);
  }
}
