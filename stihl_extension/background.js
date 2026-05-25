// Service worker — makes API calls to ssc.stihl.com (bypasses CORS).

const BASE = 'https://ssc.stihl.com/backend/api';

const TARGET_PARTS = {
  'Air Filter':    ['air filter'],
  'Pre-Filter':    ['pre-filter', 'prefilter', 'foam filter'],
  'Spark Plug':    ['spark plug'],
  'Fuel Filter':   ['fuel filter'],
  'Pickup Body':   ['pickup body', 'pickup tube', 'suction head'],
  'Primer Bulb':   ['primer bulb', 'primer'],
  'Carburetor':    ['carburetor', 'carburettor'],
};

function authHeaders(token) {
  return { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };
}

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
    const pn   = obj.partNumber || obj.materialNumber || obj.itemNumber || obj.part_number || '';
    const name = obj.name || obj.description || obj.partName || '';
    if (pn && name && !seen.has(String(pn))) {
      seen.add(String(pn));
      parts.push({
        pn:   String(pn).trim(),
        name: String(name).trim(),
        from: String(obj.serialFrom || obj.fromSerial || '').trim(),
        to:   String(obj.serialTo   || obj.toSerial   || '').trim(),
      });
    }
    Object.values(obj).forEach(v => { if (v && typeof v === 'object') walk(v); });
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
      return s.includes(',') || s.includes('"') || s.includes('\n')
        ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(',')
  ).join('\r\n');
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  if (msg.type === 'VERIFY_MODEL') {
    fetchParts(msg.materialNumber, msg.token)
      .then(data => {
        const parts = extractParts(data);
        // Try to find a model name in the response
        let modelName = '';
        function findName(obj) {
          if (!obj || typeof obj !== 'object') return;
          for (const k of ['modelName','productName','designation','model','productDesignation']) {
            if (obj[k] && typeof obj[k] === 'string' && obj[k].length < 60) {
              modelName = obj[k].trim(); return;
            }
          }
          Object.values(obj).forEach(v => { if (!modelName && v && typeof v === 'object') findName(v); });
        }
        findName(data);
        sendResponse({ ok: true, partCount: parts.length, modelName });
      })
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (msg.type === 'BUILD_MATRIX') {
    const { models, token } = msg;
    const entries = Object.entries(models);
    const headers = ['Model'];
    for (const cat of Object.keys(TARGET_PARTS)) headers.push(cat, `${cat} Note`);

    (async () => {
      const rows = [headers];
      const progress = [];
      for (const [name, materialNumber] of entries) {
        try {
          const data  = await fetchParts(materialNumber, token);
          const parts = extractParts(data);
          const row   = [name];
          for (const [, keywords] of Object.entries(TARGET_PARTS)) {
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

});
