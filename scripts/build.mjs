import fs from 'node:fs';
for (const file of ['web/index.html', 'web/app.js', 'web/style.css', 'netlify/functions/api.mjs', 'netlify/functions/pulse.mjs']) if (!fs.existsSync(file)) throw Error(`Missing ${file}`);
// Netlify publishes ONLY web/. Never copy .env, research files or server source to public assets.
for (const entry of fs.readdirSync('web')) if (!['index.html', 'app.js', 'style.css'].includes(entry)) throw Error(`Unexpected public file: ${entry}`);
console.log('Static site checked. Netlify bundles server-side functions separately.');
