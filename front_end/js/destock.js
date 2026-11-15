// Destocking Advisor page logic. Talks to the Flask backend (same origin): /api/meta, /api/advice, /api/history
const $ = (id) => document.getElementById(id);
let priceChart = null, arrivalChart = null, tr = {}, lastAdvice = false;
const lang = () => localStorage.getItem('lang') || 'en';
const fmt = (n) => (n == null ? '--' : Number(n).toLocaleString('en-US'));

// mobile menu
(function () {
  const t = $('menuToggle'), s = $('sidebar'), o = $('overlay');
  if (t && s && o) {
    t.addEventListener('click', () => { s.classList.toggle('open'); o.classList.toggle('active'); });
    o.addEventListener('click', () => { s.classList.remove('open'); o.classList.remove('active'); });
  }
})();

async function loadStrings() {
  try {
    const r = await fetch(`lang/${lang()}.json`);
    tr = (await r.json()).destock || {};
  } catch (e) { tr = {}; }
}

// Climate information card. Informational only: it never changes the sell/hold numbers. Strings come from lang/*.json (am/om are drafts).
let climateData = null;
function renderClimate(c) {
  climateData = c || climateData;
  c = climateData;
  const box = $('climateCard');
  if (!box || !c) return;
  const L = lang();
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[ch]));
  const T = (k, dflt, vars) => { let s = (tr && tr[k]) || dflt; Object.keys(vars || {}).forEach((v) => { s = s.split('{' + v + '}').join(vars[v]); }); return s; };
  const rows = [];
  const o = c.official_outlook || {};
  if (o.summary) {
    const summary = o['summary_' + L] || o.summary, risks = o['risks_' + L] || o.risks, season = o['season_' + L] || o.season;
    const meta = T('climate_issued', '{source}; issued {issued}, {age} days ago', { source: o.source, issued: o.issued, age: o.age_days });
    rows.push(`<b>${esc(T('climate_official', 'Official {season} outlook', { season }))}:</b> ${esc(summary)} <i>(${esc(meta)}${o.verified_by_human ? '' : '; ' + esc(T('climate_unchecked', 'not yet checked by a person'))}).</i> ${esc(risks || '')}`);
  }
  const ob = c.observed || {};
  if (ob.rain || ob.vegetation) {
    const bits = [];
    if (ob.rain && ob.rain.r3q != null) bits.push(T('climate_obs_rain', 'rainfall of the last 3 months is {r3}% of average', { r3: Math.round(ob.rain.r3q) }));
    if (ob.vegetation && ob.vegetation.viq != null) bits.push(T('climate_obs_veg', 'vegetation is {viq}% of average', { viq: Math.round(ob.vegetation.viq) }));
    const age = Math.max((ob.rain || {}).age_days || 0, (ob.vegetation || {}).age_days || 0);
    const when = T('climate_obs_date', 'latest data {date} ({age} days old)', { date: (ob.rain || ob.vegetation).dekad, age });
    const word = ob.reading ? ' &mdash; <b>' + esc(T('rd_' + ob.reading, ob.reading)) + '</b>' : '';
    rows.push(`<b>${esc(T('climate_obs', 'Observed conditions'))} (${esc(ob.area_label || '')}):</b> ${esc(bits.join('; '))}${word}. <i>${esc(when)}${ob.stale ? ' &#9888;' : ''}</i>`);
  } else if (ob.status === 'not_loaded') {
    rows.push(esc(T('climate_not_loaded', 'Observed rainfall and vegetation data is not loaded yet.')));
  }
  const e = c.enso || {};
  if (e.oni != null) {
    const ph = T('ph_' + e.phase, e.phase), st = e.strength ? T('st_' + e.strength, e.strength) + ' ' : '';
    const note = e.strong_el_nino_history ? ' ' + T('climate_lanina_note', e.strong_el_nino_history.note, { hit: e.strong_el_nino_history.followed_by_la_nina_within_2y, n: e.strong_el_nino_history.events }) : '';
    rows.push(`<b>${esc(T('climate_enso', 'El Niño / La Niña'))}:</b> ${esc(st + ph)} (${esc(T('climate_index', 'index {oni}, {season}', { oni: e.oni, season: e.season }))}).${esc(note)}`);
  }
  const i = c.iod || {};
  if (i.dmi != null) {
    const note = i.stale ? ' ' + T('climate_iod_stale', i.note || '', { month: i.month }) : '';
    const live = i.live ? ' ' + T('climate_iod_live', 'weekly reading, week ending {month}', { month: i.month }) + '.' : '';
    const out = (i.live && i.outlook) ? ' ' + T('climate_iod_outlook', (i.outlook || {}).text || '') : '';
    rows.push(`<b>${esc(T('climate_iod', 'Indian Ocean Dipole'))}:</b> ${esc(T('iod_' + i.phase, i.phase))} (${esc(i.dmi)}${i.live ? '' : ', ' + esc(i.month)}).${esc(live)}${esc(out)}${esc(note)}${i.stale ? ' &#9888;' : ''}`);
  }
  if ((c.enso || {}).phase === 'El Nino' && o.summary) rows.push(esc(T('climate_wet_note', 'A wet season can also bring floods and animal disease. Ask your local livestock office what to watch for.')));
  if (!rows.length) return;
  box.innerHTML = rows.map((p) => `<div style="margin:4px 0">${p}</div>`).join('') +
    `<div style="margin-top:6px;font-size:.9em"><b>${esc(T('climate_info_only', 'For information only. The sell/hold advice below does not use these.'))}</b></div>`;
  box.style.display = 'block';
}

async function init() {
  await loadStrings();
  let meta;
  try {
    const mres = await fetch('api/meta');
    if (!mres.ok) throw new Error('HTTP ' + mres.status);
    meta = await mres.json();
  } catch (e) {
    $('errorBox').style.display = 'block';
    $('errorBox').textContent = tr.offline || "Can't reach the advisor service. Open this page through the running app (for example http://localhost:5000 or your Replit /advisor/ link), not by double-clicking the file.";
    return;
  }
  const sel = $('market');
  sel.innerHTML = '';
  const groups = {};
  meta.markets.forEach((m) => {
    if (!groups[m.area]) { groups[m.area] = document.createElement('optgroup'); groups[m.area].label = m.area; sel.appendChild(groups[m.area]); }
    const o = document.createElement('option');
    o.value = m.market; o.textContent = `${m.market} (${m.records})`;
    if (m.market === meta.default_market) o.selected = true;
    groups[m.area].appendChild(o);
  });
  $('dataUntil').textContent = meta.data_report.date_to;
  const st = (meta.drought || {}).status;
  const nb = $('noModelBanner');
  if (st === 'unavailable') { nb.style.display = 'block'; nb.textContent = tr.no_model_banner || nb.textContent; }
  else if (st === 'cached_file') { nb.style.display = 'block'; nb.textContent = (tr.status_cached || 'Using a saved drought forecast ({age} day(s) old).').replace('{age}', (meta.drought.age_days == null ? '?' : meta.drought.age_days)); }
  else { nb.style.display = 'none'; }
  renderClimate(meta.climate);
  const r = meta.data_report;
  $('dataNote').textContent = (tr.note_body || 'Records {rows} from {from} to {to}, {markets} markets (oxen only). Removed {dups} duplicates and {out} unrealistic prices.')
    .replace('{rows}', r.rows_used).replace('{from}', r.date_from).replace('{to}', r.date_to)
    .replace('{markets}', r.markets).replace('{dups}', r.exact_duplicates_removed).replace('{out}', r.price_outliers_removed);
  $('runBtn').addEventListener('click', run);
  sel.addEventListener('change', drawCharts);
  const sw = $('languageSwitcher');
  if (sw) sw.addEventListener('change', async () => { await loadStrings(); if (lastAdvice) run(); drawCharts(); loadEvidence(); renderClimate(); });
  run();
  drawCharts();
  loadEvidence();
}

async function run() {
  const q = new URLSearchParams({ market: $('market').value, grade: $('grade').value, herd: $('herd').value || 1, severity: $('severity').value, lang: lang() });
  $('errorBox').style.display = 'none';
  try {
    const res = await fetch('api/advice?' + q);
    const a = await res.json();
    if (!res.ok) throw new Error(a.error || 'error');
    lastAdvice = true;
    $('resultCard').style.display = 'block';
    $('actionBadge').textContent = a.action_title;
    $('actionBadge').className = 'action ds-' + a.action + (a.conditional ? ' conditional' : '');
    $('priceNow').textContent = fmt(a.price_now_per_animal);
    $('herdValue').textContent = fmt(a.herd_value_now);
    $('waitRatio').textContent = (a.wait_vs_sell_now_ratio >= 1 ? '+' : '') + ((a.wait_vs_sell_now_ratio - 1) * 100).toFixed(1) + '%';
    $('confidence').textContent = a.confidence_label;
    $('confidence').className = 'ds-conf-' + a.confidence;
    $('reasons').innerHTML = '';
    a.reasons.forEach((t) => { const li = document.createElement('li'); li.textContent = t; $('reasons').appendChild(li); });
    // three-part confidence
    const names = { data: tr.conf_data || 'Data quality', drought: tr.conf_drought || 'Drought forecast', robustness: tr.conf_robust || 'Decision stability' };
    $('confParts').innerHTML = '';
    Object.keys(names).forEach((k) => {
      const p = a.confidence_parts[k]; const chip = document.createElement('span'); chip.className = 'chip';
      const dot = document.createElement('i'); dot.className = p.level ? 'lv-' + p.level : 'lv-na';
      chip.appendChild(dot); chip.appendChild(document.createTextNode(names[k] + ': ' + (p.label || tr.conf_na || 'n/a')));
      $('confParts').appendChild(chip);
    });
    // advice under each drought scenario
    $('scenBody').innerHTML = '';
    a.scenarios.forEach((s) => {
      const tr_ = document.createElement('tr');
      const c1 = document.createElement('td'); c1.textContent = s.name;
      const c2 = document.createElement('td'); const pill = document.createElement('span'); pill.className = 'pill ds-' + s.action; pill.textContent = s.title; c2.appendChild(pill);
      const c3 = document.createElement('td'); c3.className = 'num'; c3.textContent = ((s.wait_vs_sell_now_ratio - 1) * 100).toFixed(1) + '%';
      tr_.appendChild(c1); tr_.appendChild(c2); tr_.appendChild(c3); $('scenBody').appendChild(tr_);
    });
  } catch (e) {
    $('errorBox').style.display = 'block';
    $('errorBox').textContent = (tr.error || 'Could not get advice: ') + e.message;
  }
}

async function drawCharts() {
  const h = await (await fetch('api/history?market=' + encodeURIComponent($('market').value))).json();
  if (h.error) return;
  Chart.defaults.color = '#68736D';
  Chart.defaults.font.family = 'Inter, "Segoe UI", Arial, sans-serif';
  Chart.defaults.borderColor = '#E5E9E5';
  const colors = { 'Thin': '#9B514C', 'Moderate Weight': '#9AA39C', 'Very Fat': '#183D32' };
  const names = { 'Thin': tr.grade_thin || 'Thin', 'Moderate Weight': tr.grade_mod || 'Medium', 'Very Fat': tr.grade_fat || 'Fat' };
  const ds = ['Thin', 'Moderate Weight', 'Very Fat'].map((g) => ({
    label: names[g], data: h[g], borderColor: colors[g], backgroundColor: colors[g], spanGaps: true, tension: 0.25, pointRadius: 3,
  }));
  if (priceChart) priceChart.destroy();
  priceChart = new Chart($('priceChart'), { type: 'line', data: { labels: h.months, datasets: ds }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { x: { grid: { display: false }, border: { display: false } }, y: { border: { display: false }, grid: { color: '#E5E9E5' } } } } });
  if (arrivalChart) arrivalChart.destroy();
  arrivalChart = new Chart($('arrivalChart'), {
    type: 'bar',
    data: { labels: h.months, datasets: [{ label: tr.arrivals_label || 'Animals per report (median)', data: h.median_qty_per_report, backgroundColor: '#A9762D', borderColor: '#A9762D', borderWidth: 1 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { x: { grid: { display: false }, border: { display: false } }, y: { border: { display: false }, grid: { color: '#E5E9E5' } } } },
  });
}

async function loadEvidence() {
  try {
    const res = await fetch('api/evidence?lang=' + lang());
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const ev = await res.json();
    const box = $('evidenceList'); box.innerHTML = '';
    const stat = { measured: tr.ev_measured || 'Measured from data', tested: tr.ev_tested || 'Tested on data', partly: tr.ev_partly || 'Partly supported',
                   assumed: tr.ev_assumed || 'Assumed - no solid source', policy: tr.ev_policy || 'Policy choice', limit: tr.ev_limit || 'Known limit' };
    ev.items.forEach((it) => {
      const d = document.createElement('div'); d.className = 'ev-item';
      const head = document.createElement('div'); head.className = 'ev-head';
      const b = document.createElement('b'); b.textContent = it.label;
      const chip = document.createElement('span'); chip.className = 'ev-chip ev-' + it.status; chip.textContent = stat[it.status] || it.status;
      head.appendChild(b); head.appendChild(chip); d.appendChild(head);
      const note = document.createElement('p'); note.className = 'ev-note'; note.textContent = it.note + (it.measured_value ? ' (' + it.measured_value + ')' : ''); d.appendChild(note);
      if (it.sensitivity_pct != null) {
        const s = document.createElement('div'); s.className = 'ev-sens';
        s.textContent = (tr.ev_sens || 'Advice changes in {pct}% of stress tests when this is nudged').replace('{pct}', it.sensitivity_pct); d.appendChild(s);
      }
      if (it.sources.length) {
        const ul = document.createElement('ul'); ul.className = 'ev-src';
        it.sources.forEach((s) => {
          const li = document.createElement('li');
          if (s.url) { const a = document.createElement('a'); a.href = s.url; a.target = '_blank'; a.rel = 'noopener'; a.textContent = s.title; li.appendChild(a); }
          else { li.appendChild(document.createTextNode(s.title)); }
          const sm = document.createElement('small'); sm.textContent = ' - ' + s.says + ' [' + s.type + (s.checked_by_human ? '' : '; ' + (tr.ev_unchecked || 'found by search, not yet checked') ) + ']';
          li.appendChild(sm); ul.appendChild(li);
        });
        d.appendChild(ul);
      }
      box.appendChild(d);
    });
    $('evCandidates').textContent = ev.candidates_waiting ? (tr.ev_candidates || '{n} candidate source(s) from Probe are waiting for your review. They do not affect the advice.').replace('{n}', ev.candidates_waiting) : '';
  } catch (e) { /* evidence card is optional */ }
}

init();
