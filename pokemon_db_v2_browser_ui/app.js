const state = {
  apiBase: localStorage.getItem('saveroomApiBase') || 'http://127.0.0.1:8765',
  lastResults: [],
  selectedDetail: null,
};

const $ = (id) => document.getElementById(id);
const apiBaseInput = $('apiBase');
const apiStatus = $('apiStatus');
const searchForm = $('searchForm');
const resultsEl = $('results');
const summaryEl = $('summary');
const copyResultsBtn = $('copyResultsBtn');
const batchPriceBtn = $('batchPriceBtn');
const pricingDashboardEl = $('pricingDashboard');
const batchPriceStatus = $('batchPriceStatus');
const detailDialog = $('detailDialog');
const modalBody = $('modalBody');
const modalTitle = $('modalTitle');
const modalKicker = $('modalKicker');
const toast = $('toast');

apiBaseInput.value = state.apiBase;

function apiBase() {
  const value = apiBaseInput.value.trim().replace(/\/$/, '');
  localStorage.setItem('saveroomApiBase', value);
  return value;
}

function qs(params) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') query.set(key, value);
  }
  return query.toString();
}

async function getJson(path) {
  const response = await fetch(`${apiBase()}${path}`);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text.slice(0, 300)}`);
  }
  return response.json();
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 1800);
}

function displaySet(card) {
  const set = card.set || {};
  return set.resolved_set_name || set.core_set_name || set.resolved_set_id || set.core_set_id || 'Unknown set';
}

function languageLabel(card) {
  return card.language_name || card.language_code || 'Unknown language';
}

function imageStatus(card) {
  const images = card.images || {};
  if (images.has_exact_image) return { label: 'Exact image', className: 'exact' };
  if (images.has_display_image) return { label: 'Fallback image', className: 'fallback' };
  return { label: 'No image', className: 'missing' };
}

function productTitle(card) {
  const setName = displaySet(card);
  const number = card.collector_number ? ' — ' + card.collector_number : '';
  const lang = languageLabel(card);
  return (card.name || 'Unknown card') + number + ' — ' + setName + ' — ' + lang + ' Pokémon Card';
}

function displayImageUrl(card) {
  const images = card.images || {};
  // Prefer signed URL — works in <img> tags without auth headers
  if (images.signed_image_url) {
    return images.signed_image_url.startsWith('http') ? images.signed_image_url : apiBase() + images.signed_image_url;
  }
  // Fall back to card-level signed_image_url (search response)
  if (card.signed_image_url) {
    return card.signed_image_url.startsWith('http') ? card.signed_image_url : apiBase() + card.signed_image_url;
  }
  const local = images.local_display_image_url;
  if (local) return local.startsWith('http') ? local : apiBase() + local;
  return images.display_image_url || images.exact_image_url || null;
}

function priceBadgeHtml(price) {
  if (!price) return '';
  const parts = [];
  if (price.sold_listings > 0) parts.push('<span class="price-sold">Sold: £' + (price.sold_avg || '?') + ' avg (' + price.sold_listings + ')</span>');
  if (price.active_listings > 0) parts.push('<span class="price-active">Active: £' + (price.active_avg || '?') + ' avg (' + price.active_listings + ')</span>');
  if (parts.length === 0) return '<div class="price-none">No price data</div>';
  return '<div class="price-badge">' + parts.join(' · ') + '</div>';
}

function renderResults(results) {
  resultsEl.innerHTML = '';
  const template = $('cardTemplate');
  for (const card of results) {
    const node = template.content.cloneNode(true);
    const article = node.querySelector('.card');
    const btn = node.querySelector('.card-click');
    const img = node.querySelector('.thumb');
    const noImage = node.querySelector('.no-image');
    const badge = node.querySelector('.image-badge');
    const status = imageStatus(card);

    node.querySelector('.card-name').textContent = card.name || 'Unknown card';
    node.querySelector('.set-line').textContent = displaySet(card);
    node.querySelector('.meta-line').textContent = languageLabel(card) + ' · #' + (card.collector_number || '?') + ' · ' + card.card_id;
    node.querySelector('.rarity-line').textContent = card.card?.rarity || card.card?.category || 'No rarity/category';
    badge.textContent = status.label;
    badge.dataset.status = status.className;

    const imageUrl = displayImageUrl(card);
    if (imageUrl) {
      img.src = imageUrl;
      img.alt = (card.name || 'Card') + ' image';
      noImage.hidden = true;
      img.onerror = () => { img.hidden = true; noImage.hidden = false; noImage.textContent = 'Image failed'; };
    } else { img.hidden = true; noImage.hidden = false; }

    // Price badge from search results (include_prices=true)
    if (card.price) {
      node.querySelector('.card-body').appendChild(document.createElement('div'));
      node.querySelector('.card-body').lastElementChild.outerHTML = priceBadgeHtml(card.price);
    }

    btn.addEventListener('click', () => openDetail(card));
    article.dataset.language = card.language_code || '';
    article.dataset.cardId = card.card_id || '';
    resultsEl.appendChild(node);
  }
}

async function runSearch(event) {
  event?.preventDefault();
  const q = $('query').value.trim();
  const language_code = $('languageCode').value;
  const core_set_id = $('coreSetId').value.trim();
  const has_display_image = $('hasImageOnly').checked ? 'true' : '';
  summaryEl.textContent = 'Searching…';
  copyResultsBtn.disabled = true;
  batchPriceBtn.disabled = true;
  try {
    const data = await getJson('/search?' + qs({ q, language_code, core_set_id, has_display_image, limit: 60, include_prices: true }));
    state.lastResults = data.results || [];
    renderResults(state.lastResults);
    summaryEl.textContent = data.count + ' result' + (data.count === 1 ? '' : 's') + ' · API ' + data.elapsed_ms + ' ms';
    copyResultsBtn.disabled = state.lastResults.length === 0;
    batchPriceBtn.disabled = state.lastResults.length === 0;
  } catch (error) {
    console.error(error);
    summaryEl.textContent = 'Search failed: ' + error.message;
    resultsEl.innerHTML = '';
  }
}

async function openDetail(summaryCard) {
  modalTitle.textContent = summaryCard.name || 'Card';
  modalKicker.textContent = languageLabel(summaryCard) + ' · ' + summaryCard.card_id;
  modalBody.innerHTML = '<p class="muted">Loading detail…</p>';
  detailDialog.showModal();
  try {
    const data = await getJson('/cards/' + encodeURIComponent(summaryCard.language_code) + '/' + encodeURIComponent(summaryCard.card_id));
    state.selectedDetail = data.detail;
    modalTitle.textContent = state.selectedDetail.name || 'Card';
    modalKicker.textContent = languageLabel(state.selectedDetail) + ' · ' + state.selectedDetail.card_id + ' · ' + data.elapsed_ms + ' ms';

    const image = displayImageUrl(state.selectedDetail);
    const imgHtml = image
      ? '<img class="detail-image" src="' + image + '" alt="' + escapeHtml(state.selectedDetail.name || 'Card') + ' image" />'
      : '<div class="detail-image no-image">No display image</div>';
    const set = state.selectedDetail.set || {};
    const rules = state.selectedDetail.rules_text || {};

    let html = '<div class="detail-grid"><div>' + imgHtml + '</div><div>';
    html += '<dl class="kv">';
    html += '<dt>Product title</dt><dd>' + escapeHtml(productTitle(state.selectedDetail)) + '</dd>';
    html += '<dt>Language</dt><dd>' + escapeHtml(languageLabel(state.selectedDetail)) + ' (' + escapeHtml(state.selectedDetail.language_code || '') + ')</dd>';
    html += '<dt>Card ID</dt><dd>' + escapeHtml(state.selectedDetail.card_id || '') + '</dd>';
    html += '<dt>Collector #</dt><dd>' + escapeHtml(state.selectedDetail.collector_number || '') + '</dd>';
    html += '<dt>Set</dt><dd>' + escapeHtml(displaySet(state.selectedDetail)) + '</dd>';
    html += '<dt>Core set</dt><dd>' + escapeHtml(set.core_set_id || '') + '</dd>';
    html += '<dt>Rarity</dt><dd>' + escapeHtml(state.selectedDetail.card?.rarity || '') + '</dd>';
    html += '<dt>Types</dt><dd>' + escapeHtml(formatValue(state.selectedDetail.card?.types)) + '</dd>';
    html += '<dt>Image</dt><dd>' + escapeHtml(state.selectedDetail.images?.display_image_source_type || 'none') + '</dd>';
    html += '<dt>Provenance</dt><dd>v2 ' + (state.selectedDetail.provenance?.v2_count ?? 0) + ' · legacy ' + (state.selectedDetail.provenance?.legacy_count ?? 0) + '</dd>';
    html += '</dl>';

    // Price section - will be populated by async fetch
    html += '<h3>UK eBay Prices</h3>';
    html += '<div id="priceSection"><p class="muted">Loading prices…</p></div>';
    html += '</div></div>';

    modalBody.innerHTML = html;
    
    await loadPriceHistory(state.selectedDetail);
  } catch (error) {
    console.error(error);
    modalBody.innerHTML = '<p class="bad">Detail failed: ' + escapeHtml(error.message) + '</p>';
  }
}


function cardPriceQuery(card) {
  const cardName = (card.name || '').replace(/[()[\]{}]/g, '').replace(/[-–—]/g, ' ').replace(/\s+/g, ' ').trim();
  const setName = (card.set || {}).core_set_name || (card.set || {}).resolved_set_name || (card.set || {}).core_set_id || '';
  const langName = card.language_name || card.language_code || '';
  const number = (card.collector_number || '').replace('/', ' ');
  let query = cardName;
  if (number) query += ' ' + number;
  if (setName && !query.toLowerCase().includes(setName.toLowerCase())) query += ' ' + setName.replace(/[()[\]{}]/g, '').trim();
  if (langName && langName.toLowerCase() !== 'english') query += ' ' + langName;
  return (query + ' Pokémon card').replace(/\s+/g, ' ').trim();
}

function renderPriceFetchResult(liveData) {
  const rec = liveData.recommendation || {};
  const sum = liveData.summary || {};
  const raw = sum.raw_clean || {};
  const rawAll = sum.raw_all || {};
  const graded = sum.graded || {};
  const all = sum.all_non_noise || {};
  if (!((raw.count || graded.count || all.count) > 0)) {
    return '<p class="muted">No usable sold listings found for this card/language on eBay UK. No English fallback is shown.</p>';
  }
  let ph = '<div class="price-recommendation">';
  ph += '<div class="price-main">Recommended raw: <strong>£' + (rec.typical_raw_price_gbp ?? 'N/A') + '</strong></div>';
  if (rec.typical_range_gbp && rec.typical_range_gbp[0]) ph += '<div class="muted">Typical raw range: £' + rec.typical_range_gbp[0] + '–£' + rec.typical_range_gbp[1] + '</div>';
  ph += '<div class="muted">' + (liveData.cached ? 'Cached result' : 'Live RapidAPI result') + ' · ' + (liveData.cost_guard?.spent_request ? '1 request used' : '0 requests used') + ' · Language: ' + escapeHtml(liveData.language || 'unspecified') + '</div>';
  ph += '</div><div class="price-grid">';
  ph += priceBox('Raw clean', raw);
  ph += priceBox('All raw', rawAll);
  ph += priceBox('Graded', graded);
  ph += priceBox('All non-noise', all);
  ph += '</div>';
  return ph;
}

async function loadPriceHistory(card) {
  const priceSec = $('priceSection');
  const query = cardPriceQuery(card);
  let html = '<div class="price-actions"><button id="fetchPriceNowBtn" class="primary" type="button">Fetch/update UK sold prices</button><p class="muted">Query: ' + escapeHtml(query) + '. Fetch uses cache when fresh; otherwise it spends 1 RapidAPI request.</p></div>';
  try {
    const hist = await getJson('/api/prices/history?' + qs({ card_id: card.card_id, language_code: card.language_code, bucket: 'raw', limit: 5 }));
    if (hist.listings && hist.listings.length) {
      html += '<h4>Recent raw sample listings</h4><ul class="listing-list">';
      for (const row of hist.listings.slice(0, 5)) {
        html += '<li><strong>£' + row.price_gbp + '</strong> ' + escapeHtml(row.raw_title || row.condition || 'listing') + ' <span class="muted">' + escapeHtml(row.sold_date || '') + ' · score ' + escapeHtml(row.confidence_score ?? '') + '</span></li>';
      }
      html += '</ul>';
    } else {
      html += '<p class="muted">No stored raw sample listings yet for this card/language. No English price fallback is shown.</p>';
    }
    const graded = await getJson('/api/prices/history?' + qs({ card_id: card.card_id, language_code: card.language_code, bucket: 'graded', limit: 1 }));
    if (graded.count) html += '<p class="muted">Graded listings stored separately: ' + graded.count + ' recent sample row(s).</p>';
  } catch (e) {
    html += '<p class="muted">Stored history unavailable: ' + escapeHtml(e.message) + '</p>';
  }
  priceSec.innerHTML = html;
  $('fetchPriceNowBtn').addEventListener('click', async () => {
    if (!confirm('Fetch UK sold prices for this card/language? Fresh cache costs 0 requests; stale/missing cache costs 1 RapidAPI request.')) return;
    priceSec.innerHTML = '<p class="muted">Fetching price data…</p>';
    try {
      const liveData = await getJson('/api/prices/fetch?' + qs({ query, max_results: 60, language: card.language_code || '', card_id: card.card_id || '' }));
      priceSec.innerHTML = renderPriceFetchResult(liveData);
      await loadPricingDashboard();
    } catch (e) {
      priceSec.innerHTML = '<p class="muted">Price fetch failed: ' + escapeHtml(e.message) + '</p>';
    }
  });
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function priceBox(label, stats) {
  if (!stats || !stats.count) return '';
  let html = '<div class="price-box price-box--sold"><h4>' + escapeHtml(label) + ' (' + stats.count + ')</h4><dl class="kv">';
  html += '<dt>Median</dt><dd>£' + (stats.median ?? 'N/A') + '</dd>';
  html += '<dt>Mean</dt><dd>£' + (stats.mean ?? 'N/A') + '</dd>';
  html += '<dt>P25–P75</dt><dd>£' + (stats.p25 ?? 'N/A') + '–£' + (stats.p75 ?? 'N/A') + '</dd>';
  html += '<dt>Min–Max</dt><dd>£' + (stats.min ?? 'N/A') + '–£' + (stats.max ?? 'N/A') + '</dd>';
  html += '</dl></div>';
  return html;
}

function formatValue(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

async function checkHealth() {
  apiStatus.textContent = 'Checking…';
  apiStatus.className = 'status muted';
  try {
    const d = await getJson('/health');
    apiStatus.textContent = d.ok ? 'API OK' : 'API reachable but support objects are not ready';
    apiStatus.className = d.ok ? 'status ok' : 'status bad';
  } catch (error) {
    apiStatus.textContent = 'API offline: ' + error.message;
    apiStatus.className = 'status bad';
  }
}


function copyText(text, message) {
  navigator.clipboard.writeText(text).then(() => showToast(message)).catch(() => showToast('Copy failed'));
}

async function postJson(path, body) {
  const response = await fetch(`${apiBase()}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text.slice(0, 300)}`);
  }
  return response.json();
}

async function loadPricingDashboard() {
  pricingDashboardEl.innerHTML = '<p class="muted">Loading pricing dashboard…</p>';
  try {
    const d = await getJson('/api/prices/dashboard?limit=10');
    const u = d.usage || {};
    const c = d.counts || {};
    let html = '';
    if (d.warning) html += '<div class="dashboard-warning">' + escapeHtml(d.warning) + '</div>';
    html += metricCard('Requests used this month', u.used_this_month + ' / ' + u.monthly_limit);
    html += metricCard('Remaining safe requests', u.remaining_before_guard);
    html += metricCard('Cached price queries', c.cached_price_queries);
    html += metricCard('Price history rows', c.price_history_rows);
    html += metricCard('Cards with sold prices', c.distinct_cards_with_sold_prices);
    html += metricCard('Cards with active prices', c.distinct_cards_with_active_prices);
    html += '<div class="dashboard-wide"><h3>Top priced cards</h3>' + tableHtml(d.top_priced_cards || [], ['card_id', 'language_code', 'name', 'avg_price', 'listing_count']) + '</div>';
    html += '<div class="dashboard-wide"><h3>Recently fetched</h3>' + tableHtml(d.recently_fetched || [], ['card_id', 'language_code', 'query', 'fetched_at']) + '</div>';
    html += '<div class="dashboard-wide"><h3>Recent failed fetches</h3>' + tableHtml(d.recent_failed_fetches || [], ['card_id', 'language_code', 'reason', 'query', 'imported_at']) + '</div>';
    pricingDashboardEl.innerHTML = html;
  } catch (e) {
    pricingDashboardEl.innerHTML = '<p class="bad">Dashboard failed: ' + escapeHtml(e.message) + '</p>';
  }
}

function metricCard(label, value) {
  return '<div class="metric-card"><span>' + escapeHtml(label) + '</span><strong>' + escapeHtml(value ?? '0') + '</strong></div>';
}

function tableHtml(rows, columns) {
  if (!rows.length) return '<p class="muted">No rows yet.</p>';
  let html = '<div class="table-wrap"><table><thead><tr>' + columns.map(c => '<th>' + escapeHtml(c) + '</th>').join('') + '</tr></thead><tbody>';
  for (const row of rows) html += '<tr>' + columns.map(c => '<td>' + escapeHtml(row[c] ?? '') + '</td>').join('') + '</tr>';
  return html + '</tbody></table></div>';
}

async function generateHighValueQueue() {
  batchPriceStatus.textContent = 'Generating high-value queue CSV…';
  try {
    const q = await getJson('/api/prices/queue/high-value?language_code=en&limit=500');
    batchPriceStatus.textContent = 'Generated ' + q.count + ' candidates; estimated new requests ' + q.estimated_new_requests + '. CSV: ' + q.report_path;
  } catch (e) {
    batchPriceStatus.textContent = 'Queue generation failed: ' + e.message;
  }
}

async function fetchVisiblePrices() {
  const visible = state.lastResults.slice(0, 50);
  if (!visible.length) return;
  batchPriceStatus.textContent = 'Estimating visible-result price fetch…';
  try {
    const estimate = await postJson('/api/prices/batch-estimate', { cards: visible, max_results: 60 });
    const msg = 'Visible cards: ' + estimate.visible_cards + '\nAlready cached/deduped: ' + estimate.already_cached + '\nEstimated new RapidAPI requests: ' + estimate.estimated_new_requests + '\nMonthly used: ' + estimate.usage.used_this_month + '/' + estimate.usage.monthly_limit + '\nRemaining guard: ' + estimate.usage.remaining_before_guard;
    if (!estimate.allowed) {
      alert(msg + '\n\nBlocked: estimated requests exceed remaining local guard.');
      batchPriceStatus.textContent = 'Batch blocked by local guard.';
      return;
    }
    if (!confirm(msg + '\n\nRun sequentially now?')) {
      batchPriceStatus.textContent = 'Batch cancelled before spending.';
      return;
    }
    let done = 0;
    let spent = 0;
    for (const item of estimate.planned) {
      if (item.cached) {
        done += 1;
        batchPriceStatus.textContent = 'Skipped cached ' + done + '/' + estimate.planned.length + ': ' + item.card_id;
        continue;
      }
      const data = await getJson('/api/prices/fetch?' + qs({ query: item.query, max_results: 60, language: item.language_code || '', card_id: item.card_id || '' }));
      if (data.cost_guard?.spent_request) spent += 1;
      done += 1;
      batchPriceStatus.textContent = 'Fetched ' + done + '/' + estimate.planned.length + ' · spent ' + spent + ' request(s) · ' + item.card_id;
      await new Promise(resolve => setTimeout(resolve, 700));
    }
    batchPriceStatus.textContent = 'Batch complete. Spent ' + spent + ' new request(s).';
    await loadPricingDashboard();
    await runSearch();
  } catch (e) {
    batchPriceStatus.textContent = 'Batch failed: ' + e.message;
  }
}

searchForm.addEventListener('submit', runSearch);
$('healthBtn').addEventListener('click', checkHealth);
$('refreshPricingDashboardBtn').addEventListener('click', loadPricingDashboard);
$('generateQueueBtn').addEventListener('click', generateHighValueQueue);
batchPriceBtn.addEventListener('click', fetchVisiblePrices);
$('closeModal').addEventListener('click', () => detailDialog.close());
copyResultsBtn.addEventListener('click', () => copyText(JSON.stringify(state.lastResults, null, 2), 'Result JSON copied'));
$('copyCardJsonBtn').addEventListener('click', () => { if (state.selectedDetail) copyText(JSON.stringify(state.selectedDetail, null, 2), 'Card JSON copied'); });
$('copyTitleBtn').addEventListener('click', () => { if (state.selectedDetail) copyText(productTitle(state.selectedDetail), 'Product title copied'); });
$('copyShopifyBtn').addEventListener('click', () => { if (state.selectedDetail) copyText(JSON.stringify({title: productTitle(state.selectedDetail), vendor: 'SaveRoom', product_type: 'Pokémon Single Card'}, null, 2), 'Shopify draft copied'); });

document.querySelectorAll('[data-example]').forEach((button) => {
  button.addEventListener('click', () => { $('query').value = button.dataset.example; $('coreSetId').value = ''; runSearch(); });
});
document.querySelectorAll('[data-set]').forEach((button) => {
  button.addEventListener('click', () => { $('query').value = ''; $('coreSetId').value = button.dataset.set; runSearch(); });
});

checkHealth();
loadPricingDashboard();
runSearch();
