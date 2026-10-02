// Glitch Loom — talking to the local server on this computer. Nothing here reaches the internet.

import { storeParam } from './store.js';

// If a `store` value is present at all, even an empty or misspelt one, the real library is never used.
export const STORE = storeParam(location.search);

function url(path, extra) {
  const p = new URLSearchParams(extra || {});
  if (STORE !== null) p.set('store', STORE);
  const s = p.toString();
  return '/api/' + path + (s ? '?' + s : '');
}

async function call(method, path, body, opts = {}) {
  let r;
  try {
    r = await fetch(url(path, opts.query), { method, headers: method === 'GET' ? {} : { 'Content-Type': 'application/json', 'X-Loom': '1' }, body: body === undefined ? undefined : JSON.stringify(body), keepalive: !!opts.keepalive, cache: 'no-store' });
  } catch (e) { const err = new Error('Loom’s local server did not answer.'); err.offline = true; throw err; }
  let data = null; try { data = await r.json(); } catch (e) { data = { error: 'Loom’s local server sent something unreadable.' }; }
  if (!r.ok) { const err = new Error(data.error || `The server answered ${r.status}.`); err.status = r.status; err.data = data; throw err; }
  return data;
}

export const api = {
  health: () => call('GET', 'health'),
  engine: fresh => call('GET', 'engine', undefined, fresh ? { query: { fresh: '1' } } : {}),
  library: () => call('GET', 'library'),
  setCurrent: id => call('POST', 'library/current', { id }),
  create: body => call('POST', 'courses', body),
  get: id => call('GET', 'courses/' + id),
  put: (id, body, opts) => call('PUT', 'courses/' + id, body, opts),
  rename: (id, name) => call('POST', `courses/${id}/name`, { name }),
  restore: bundle => call('POST', 'restore', bundle),
  archive: (id, archived) => call('POST', `courses/${id}/archive`, { archived }),
  duplicate: id => call('POST', `courses/${id}/duplicate`, {}),
  saveImport: body => call('POST', 'imports', body),
  findImport: body => call('POST', 'imports/find', body),
  engineGet: id => call('GET', `courses/${id}/engine`),
  ideas: id => call('GET', `courses/${id}/ideas`),
  engineDo: (id, body) => call('POST', `courses/${id}/engine`, body),
  engineStop: id => call('POST', `courses/${id}/engine/stop`, {}),
  // Deciding between two answers the review already gave. It asks nothing of the model, so it is not an
  // engine action and does not wait for the Claude tool to be ready.
  decideAttribution: (id, body) => call('POST', `courses/${id}/attribution-resolution`, body),
  // Correcting one `requires` line that is not really a prerequisite. Asks nothing of the model.
  correctMapEdge: (id, body) => call('POST', `courses/${id}/map-correction`, body),
  saveExport: (id, body) => call('POST', `courses/${id}/exports`, body),
  backupUrl: id => url(`courses/${id}/backup`),
  importUrl: hash => url(`imports/${hash}`)
};
