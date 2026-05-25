let token     = '';
let models    = {};   // { displayName: materialNumber }

const tokenDot     = document.getElementById('tokenDot');
const tokenMsg     = document.getElementById('tokenMsg');
const searchInput  = document.getElementById('searchInput');
const searchBtn    = document.getElementById('searchBtn');
const searchRes    = document.getElementById('searchResults');
const modelListEl  = document.getElementById('modelList');
const buildBtn     = document.getElementById('buildBtn');
const statusEl     = document.getElementById('status');

// ── init ──────────────────────────────────────────────────────────────────────

async function init() {
  const stored = await chrome.storage.local.get(['models', 'token']);
  models = stored.models || {};
  renderModelList();

  // Try to grab a fresh token from any open Stihl portal tab
  const freshToken = await getTokenFromTab();
  if (freshToken) {
    token = freshToken;
    await chrome.storage.local.set({ token });
    setTokenOk();
  } else if (stored.token) {
    token = stored.token;
    setTokenOk('Saved token — open portal to refresh');
  } else {
    setTokenErr();
  }
}

async function getTokenFromTab() {
  try {
    const tabs = await chrome.tabs.query({ url: 'https://ssc.stihl.com/*' });
    if (!tabs.length) return null;
    const resp = await chrome.tabs.sendMessage(tabs[0].id, { type: 'GET_TOKEN' });
    return resp?.token || null;
  } catch {
    return null;
  }
}

function setTokenOk(msg) {
  tokenDot.className = 'ok';
  tokenMsg.textContent = msg || 'Logged in ✓';
  tokenMsg.className = 'ok';
  searchBtn.disabled = false;
}

function setTokenErr() {
  tokenDot.className = 'err';
  tokenMsg.innerHTML = 'Not logged in — <a href="https://ssc.stihl.com" target="_blank">open the Stihl portal</a> first';
  tokenMsg.className = 'err';
  searchBtn.disabled = true;
}

// ── search ────────────────────────────────────────────────────────────────────

searchBtn.addEventListener('click', doSearch);
searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });

function doSearch() {
  const q = searchInput.value.trim();
  if (!q || !token) return;

  searchBtn.disabled = true;
  searchBtn.innerHTML = '<span class="spin">↻</span>';
  searchRes.style.display = 'none';
  setStatus('');

  chrome.runtime.sendMessage({ type: 'SEARCH_MODEL', query: q, token }, (resp) => {
    searchBtn.disabled = false;
    searchBtn.textContent = 'Search';

    if (!resp) {
      setStatus('No response from background.', true);
      return;
    }

    if (!resp.ok || !resp.results?.length) {
      // No search API found — fall back to manual material number entry
      showManualFallback(q);
      return;
    }

    showSearchResults(resp.results);
  });
}

function showSearchResults(results) {
  searchRes.innerHTML = results.slice(0, 8).map((r, i) =>
    `<div class="result-item" data-idx="${i}">
       <div class="result-name">${r.name}</div>
       <div class="result-mn">${r.materialNumber}</div>
     </div>`
  ).join('');
  searchRes.style.display = 'block';

  searchRes.querySelectorAll('.result-item').forEach((el, i) => {
    el.addEventListener('click', () => addModel(results[i].name, results[i].materialNumber));
  });
}

function showManualFallback(modelName) {
  searchRes.innerHTML = `
    <div id="noResults">
      <div style="margin-bottom:8px;color:#aaa;">
        Search not available — enter the material number manually.<br>
        <span style="font-size:11px;color:#666;">
          Find it: on the Stihl portal, open the model's page, look in the URL
          or DevTools → Network → any /spareParts request → request body.
        </span>
      </div>
      <div style="display:flex;gap:6px;align-items:center;">
        <input id="manualMn" type="text" placeholder="e.g. 42830111610"
          style="flex:1;background:#111;border:1px solid #444;border-radius:5px;
                 color:#fff;font-size:13px;padding:6px 8px;">
        <button id="manualAdd"
          style="padding:6px 12px;border-radius:5px;border:none;cursor:pointer;
                 background:#3b82f6;color:#fff;font-size:13px;font-weight:500;">
          Add
        </button>
      </div>
    </div>`;
  searchRes.style.display = 'block';

  document.getElementById('manualAdd').addEventListener('click', () => {
    const mn = document.getElementById('manualMn').value.trim();
    if (!mn.match(/^\d{8,15}$/)) {
      setStatus('Enter a valid material number (8–15 digits).', true);
      return;
    }
    addModel(modelName, mn);
  });
}

// ── add model ─────────────────────────────────────────────────────────────────

async function addModel(name, materialNumber) {
  searchRes.style.display = 'none';
  setStatus(`Adding ${name}…`);

  models[name] = materialNumber;
  await chrome.storage.local.set({ models });
  renderModelList();
  setStatus(`Added: ${name}`);
  searchInput.value = '';
}

// ── model list ─────────────────────────────────────────────────────────────────

function renderModelList() {
  const names = Object.keys(models);
  buildBtn.disabled = names.length === 0;
  if (!names.length) {
    modelListEl.innerHTML = '<div id="emptyMsg">Search for models above to add them</div>';
    return;
  }
  modelListEl.innerHTML = names.map(n => `
    <div class="model-row">
      <span class="model-row-name" title="${n}">${n}</span>
      <span class="model-row-mn">${models[n]}</span>
      <button class="remove-btn" data-name="${n}">×</button>
    </div>`).join('');

  modelListEl.querySelectorAll('.remove-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      delete models[btn.dataset.name];
      await chrome.storage.local.set({ models });
      renderModelList();
      setStatus('');
    });
  });
}

// ── build CSV ─────────────────────────────────────────────────────────────────

buildBtn.addEventListener('click', () => {
  if (!token) { setStatus('Open the Stihl portal first.', true); return; }

  buildBtn.disabled = true;
  buildBtn.innerHTML = '<span class="spin">↻</span> Fetching parts…';
  setStatus('');

  chrome.runtime.sendMessage({ type: 'BUILD_MATRIX', models, token }, (resp) => {
    buildBtn.disabled = false;
    buildBtn.textContent = 'Build & Download CSV';

    if (!resp?.ok) {
      setStatus('Something went wrong. Try refreshing the Stihl portal.', true);
      return;
    }

    const expired = resp.progress.some(p => !p.ok && p.error?.includes('401'));
    if (expired) {
      setStatus('Token expired — open the Stihl portal and reopen this extension.', true);
      return;
    }

    const blob = new Blob([resp.csv], { type: 'text/csv' });
    const a = Object.assign(document.createElement('a'), {
      href: URL.createObjectURL(blob), download: 'stihl_parts_matrix.csv'
    });
    a.click();

    const ok  = resp.progress.filter(p => p.ok).length;
    const bad = resp.progress.filter(p => !p.ok).length;
    setStatus(bad ? `Done — ${ok} ok, ${bad} failed` : `Done! ${ok} models exported ✓`);
  });
});

// ── helpers ───────────────────────────────────────────────────────────────────

function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.className = isError ? 'err' : (msg ? 'ok' : '');
}

init();
