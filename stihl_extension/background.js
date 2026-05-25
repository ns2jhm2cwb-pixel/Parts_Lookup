const BASE = 'https://ssc.stihl.com/backend/api';

const TARGET_PARTS = {
  'Air Filter':   ['air filter'],
  'Pre-Filter':   ['pre-filter', 'prefilter', 'foam filter'],
  'Spark Plug':   ['spark plug'],
  'Fuel Filter':  ['fuel filter'],
  'Pickup Body':  ['pickup body', 'pickup tube', 'suction head'],
  'Primer Bulb':  ['primer bulb', 'primer'],
  'Carburetor':   ['carburetor', 'carburettor'],
};

function authHeaders(token) {
  return { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };
}

// ── model search ──────────────────────────────────────────────────────────────

// Ordered list of endpoints to try. First one that returns usable results wins.
const SEARCH_ATTEMPTS = [
  (q, t) => fetch(`${BASE}/v2/products?search=${encodeURIComponent(q)}&country=US&preferredLanguage=en`,
                  { headers: authHeaders(t) }),
  (q, t) => fetch(`${BASE}/v2/models?search=${encodeURIComponent(q)}&country=US&preferredLanguage=en`,
                  { headers: authHeaders(t) }),
  (q, t) => fetch(`${BASE}/v2/articles?search=${encodeURIComponent(q)}&country=US&preferredLanguage=en`,
                  { headers: authHeaders(t) }),
  (q, t) => fetch(`${BASE}/v1/products?search=${encodeURIComponent(q)}&country=US&preferredLanguage=en`,
                  { headers: authHeaders(t) }),
  (q, t) => fetch(`${BASE}/v2/products/search`, {
              method: 'POST', headers: authHeaders(t),
              body: JSON.stringify({ search: q, country: 'US', preferredLanguage: 'en' }) }),
  (q, t) => fetch(`${BASE}/v2/spareParts/models?search=${encodeURIComponent(q)}&country=US&preferredLanguage=en`,
                  { headers: authHeaders(t) }),
];

function parseSearchResults(data) {
  const results = [];
  const seen = new Set();

  function walk(obj) {
    if (Array.isArray(obj)) { obj.forEach(walk); return; }
    if (!obj || typeof obj !== 'object') return;

    const mn = obj.materialNumber || obj.material_number || obj.productId ||
               obj.articleNumber  || obj.id;
    const name = obj.name || obj.productName || obj.designation ||
                 obj.modelName || obj.title || obj.description;

    if (mn && String(mn).match(/^\d{8,15}$/) && name && !seen.has(String(mn))) {
      seen.add(String(mn));
      results.push({ name: String(name).trim(), materialNumber: String(mn).trim() });
    } else {
      for (const v of Object.values(obj)) {
        if (v && typeof v === 'object') walk(v);
      }
    }
  }

  walk(data);
  return results;
}

async function searchModels(query, token) {
  for (const attempt of SEARCH_ATTEMPTS) {
    try {
      const r = await attempt(query, token);
      if (!r.ok) continue;
      const data = await r.json();
      const results = parseSearchResults(data);
      if (results.length > 0) return { ok: true, results };
    } catch { /* try next */ }
  }
  return { ok: false, results: [] };
}

// ── parts fetching ────────────────────────────────────────────────────────────

async function fetchParts(materialNumber, token) {
  const r = await fetch(`${BASE}/v2/spareParts`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ materialNumbers: [materialNumber], country: 'US', preferredLanguage: 'en' }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

function extractParts(data) {
  const parts = [], seen = new Set();

  function walk(obj) {
    if (Array.isArray(obj)) { obj.forEach(walk); return; }
    if (!obj || typeof obj !== 'object') return;

    const pn = obj.partNumber || obj.part_number || obj.itemNumber;
    const name = obj.name || obj.description || obj.partName;

    if (pn && name && !seen.has(String(pn))) {
      seen.add(String(pn));
      parts.push({
        pn:   String(pn).trim(),
        name: String(name).trim(),
        from: String(obj.serialFrom || obj.fromSerial || '').trim(),
        to:   String(obj.serialTo   || obj.toSerial   || '').trim(),
      });
    }
    for (const v of Object.values(obj)) {
      if (v && typeof v === 'object') walk(v);
    }
  }

  walk(data);
  return parts;
}

function serialNote(p) {
  if (p.from && p.to) return `serial ${p.from}–${p.to}`;
  if (p.from) return `from serial ${p.from}`;
  if (p.to)   return `up to serial ${p.to}`;
  return '';
}

function findPart(parts, keywords) {
  for (const kw of keywords)
    for (const p of parts)
      if (p.name.toLowerCase().includes(kw.toLowerCase())) return p;
  return null;
}

function toCSV(rows) {
  return rows.map(row =>
    row.map(cell => {
      const s = String(cell ?? '');
      return /[,"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(',')
  ).join('\r\n');
}

// ── message handler ───────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  if (msg.type === 'SEARCH_MODEL') {
    searchModels(msg.query, msg.token)
      .then(sendResponse)
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (msg.type === 'BUILD_MATRIX') {
    const { models, token } = msg;
    const headers = ['Model'];
    for (const cat of Object.keys(TARGET_PARTS)) headers.push(cat, `${cat} Note`);

    (async () => {
      const rows = [headers], progress = [];
      for (const [name, materialNumber] of Object.entries(models)) {
        try {
          const data  = await fetchParts(materialNumber, token);
          const parts = extractParts(data);
          const row   = [name];
          for (const keywords of Object.values(TARGET_PARTS)) {
            const match = findPart(parts, keywords);
            row.push(match ? match.pn : '', match ? serialNote(match) : '');
          }
          rows.push(row);
          progress.push({ name, ok: true, count: parts.length });
        } catch (err) {
          rows.push([name, ...Array(headers.length - 1).fill('')]);
          progress.push({ name, ok: false, error: err.message });
        }
      }
      sendResponse({ ok: true, csv: toCSV(rows), progress });
    })();
    return true;
  }

  // Dump raw JSON for a model — for debugging field names
  if (msg.type === 'DUMP_PARTS') {
    fetchParts(msg.materialNumber, msg.token)
      .then(data => sendResponse({ ok: true, data }))
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true;
  }

});
