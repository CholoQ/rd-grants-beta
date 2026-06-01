'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const searchStateKey = 'rdFundingSearchState:v1';

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function getQueryId() {
  const params = new URLSearchParams(location.search);
  return (params.get('id') || '').trim();
}

function cachedSearchItem(id) {
  try {
    const state = JSON.parse(localStorage.getItem(searchStateKey) || 'null');
    const items = state && Array.isArray(state.items) ? state.items : [];
    return items.find(item => String(item.id) === String(id)) || null;
  } catch (_) {
    return null;
  }
}

async function api(path) {
  const res = await fetch(path, { headers: { 'Accept': 'application/json' } });
  if (!res.ok) {
    let msg = '取得に失敗しました';
    try { const j = await res.json(); if (j && j.error) msg = j.error; } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
}

function summarizeRiskLevel(risks) {
  if (!Array.isArray(risks) || !risks.length) return { label: '要確認', cls: 'unknown' };
  if (risks.some(r => r && r.level === 'high')) return { label: '高', cls: 'high' };
  if (risks.some(r => r && r.level === 'medium')) return { label: '中', cls: 'mid' };
  return { label: '低', cls: 'low' };
}

function expertLevelLabel(level) {
  if (level === 'high') return '相談を強く検討';
  if (level === 'recommended') return '相談を検討';
  if (level === 'optional') return '必要に応じて検討';
  return '要確認';
}

function fact(label, value) {
  const text = (value == null || value === '' || value === '要確認') ? '—' : value;
  return `<div class="detail-fact"><span class="detail-fact__label">${escapeHtml(label)}</span><span class="detail-fact__value">${escapeHtml(text)}</span></div>`;
}

function formatYen(n) {
  if (!n && n !== 0) return '';
  if (n >= 100000000) return `${(n / 100000000).toLocaleString()}億円`;
  if (n >= 10000) return `${(n / 10000).toLocaleString()}万円`;
  return `${n.toLocaleString()}円`;
}

function renderList(el, items, emptyText = '本文からは具体項目を読み取れませんでした') {
  if (!el) return;
  const arr = Array.isArray(items) ? items.filter(x => x && String(x).trim() && String(x) !== '要確認') : [];
  if (!arr.length) {
    el.innerHTML = `<li class="detail-list__empty">${escapeHtml(emptyText)}</li>`;
    return;
  }
  el.innerHTML = arr.map(x => `<li>${escapeHtml(String(x))}</li>`).join('');
}

function renderRisks(el, risks) {
  if (!el) return;
  if (!Array.isArray(risks) || !risks.length) {
    el.innerHTML = '<li class="detail-list__empty">大きな対象外リスクは見つかりませんでした</li>';
    return;
  }
  el.innerHTML = risks.map(r => {
    const level = r && r.level ? r.level : 'low';
    const label = r && r.label ? r.label : '';
    return `<li class="detail-risk detail-risk--${escapeHtml(level)}"><span class="detail-risk__level">${escapeHtml(level === 'high' ? '高' : level === 'medium' ? '中' : '低')}</span><span class="detail-risk__text">${escapeHtml(label)}</span></li>`;
  }).join('');
}

function renderTags(el, items) {
  if (!el) return;
  const arr = Array.isArray(items) ? items.filter(x => x && String(x).trim()) : [];
  if (!arr.length) { el.innerHTML = '<li class="detail-list__empty">必要に応じて相談</li>'; return; }
  el.innerHTML = arr.map(x => `<li class="detail-tag">${escapeHtml(String(x))}</li>`).join('');
}

function setOfficialLinks(url) {
  if (!url) return;
  const top = $('#detailOfficialBtn');
  if (top) { top.href = url; top.hidden = false; }
  const bottom = $('#detailOfficialBtnBottom');
  if (bottom) { bottom.href = url; bottom.hidden = false; }
}

const loadingMessages = [
  ['りこが公募要領を読んでます', '対象条件、使える経費、注意点を順番に拾っています。'],
  ['対象になる会社を確認しています', '会社規模、地域、フェーズのズレがないか見ています。'],
  ['必要書類をほどいています', '「書類一式」で終わらないように、具体名を探しています。'],
  ['応募前のひっかかりを整理しています', '対象外リスクと準備の重さを、やさしく短くまとめます。'],
];
let loadingTimer = null;
let loadingIndex = 0;

function setLoadingMessage(index) {
  const msg = loadingMessages[index % loadingMessages.length];
  const title = $('#detailLoadingTitle');
  const text = $('#detailLoadingText');
  if (title) title.textContent = msg[0];
  if (text) text.textContent = msg[1];
}

function startLoading() {
  const box = $('#detailLoading');
  if (!box) return;
  loadingIndex = 0;
  setLoadingMessage(loadingIndex);
  box.hidden = false;
  clearInterval(loadingTimer);
  loadingTimer = setInterval(() => {
    loadingIndex += 1;
    setLoadingMessage(loadingIndex);
  }, 2600);
}

function stopLoading() {
  clearInterval(loadingTimer);
  loadingTimer = null;
  const box = $('#detailLoading');
  if (box) box.hidden = true;
}

function renderShellFromItem(item) {
  if (!item) return;
  $('#detailEyebrow').textContent = item.institution_name || item.system_name || item.source || '公募情報';
  $('#detailTitle').textContent = item.title || '名称未設定の公募';
  $('#detailCatch').textContent = item.match_summary || item.detail_plain || item.subsidy_catch_phrase || '公募本文を読み取っています。';
  const official = item.official_url || item.safe_public_url || item.front_subsidy_detail_page_url || '';
  setOfficialLinks(official);
  const subsidyMax = item.subsidy_max_limit ? formatYen(item.subsidy_max_limit) : '';
  $('#detailFacts').innerHTML = [
    fact('実施機関', item.institution_name || item.system_name || item.source || ''),
    fact('対象地域', item.target_area_search || ''),
    fact('補助上限', subsidyMax),
    fact('補助率', item.subsidy_rate || ''),
    fact('締切', item.acceptance_end_datetime || ''),
    fact('状態', item.status || ''),
  ].join('');
}

function updateJudgement(summary) {
  const risk = summarizeRiskLevel(summary.exclusion_risks);
  const diff = summary.difficulty || {};
  const prep = summary.prep_load || {};
  const expert = summary.expert_needed || {};
  const set = (key, text, cls) => {
    const el = document.querySelector(`#detailJudgement [data-j="${key}"]`);
    if (!el) return;
    el.textContent = text;
    if (cls) el.className = `j-badge j-badge--${key} j-badge--${key}-${cls}`;
  };
  set('risk', `🚫 対象外リスク：${risk.label}`, risk.cls);
  set('diff', `🪜 申請難易度：${diff.label || '要確認'}`, diff.score ? `s${diff.score}` : 'unknown');
  set('prep', `⏳ 準備期間：${prep.label || '要確認'}`);
  set('expert', `🙋 専門家相談：${expertLevelLabel(expert.level)}`, expert.level || 'unknown');
}

function render(data) {
  const summary = (data && data.summary) || {};
  const s = summary;

  $('#detailEyebrow').textContent = s.field || '研究開発支援';
  $('#detailTitle').textContent = data.title || '名称未設定の公募';
  $('#detailCatch').textContent = s.overview || s.purpose || '公募本文から概要を読み取れませんでした。';

  const budgetText = s.budget || '';
  const deadlineText = s.deadline || '';
  const subsidyMax = data.subsidy_max_limit ? formatYen(data.subsidy_max_limit) : '';
  const region = data.target_area_search || '';
  const institution = data.institution_name || data.system_name || data.source || '';
  $('#detailFacts').innerHTML = [
    fact('実施機関', institution),
    fact('対象地域', region),
    fact('補助上限', subsidyMax),
    fact('補助率', data.subsidy_rate || ''),
    fact('締切', deadlineText),
    fact('予算（要約）', budgetText),
  ].join('');
  const sourceNote = $('#detailSourceNote');
  if (sourceNote) sourceNote.textContent = data.pdf_note || '';

  const official = data.official_url || data.front_subsidy_detail_page_url || data.safe_public_url || '';
  setOfficialLinks(official);

  const detailId = getQueryId();
  if (detailId) {
    const c1 = $('#detailCheckBtn');       if (c1 && c1.tagName === 'A') c1.href = '/check.html?id=' + encodeURIComponent(detailId);
    const c2 = $('#detailCheckBtnBottom'); if (c2 && c2.tagName === 'A') c2.href = '/check.html?id=' + encodeURIComponent(detailId);
  }

  updateJudgement(summary);

  renderRisks($('#detailRisks'), s.exclusion_risks);

  const diffReasons = (s.difficulty && Array.isArray(s.difficulty.reasons)) ? s.difficulty.reasons : [];
  renderList($('#detailDifficultyReasons'), diffReasons);

  const targetConditions = Array.isArray(s.target_conditions) ? s.target_conditions : (s.target_conditions ? [s.target_conditions] : []);
  renderList($('#detailTargetConditions'), targetConditions);

  renderList($('#detailEligibleExpenses'), Array.isArray(s.eligible_expenses) ? s.eligible_expenses : [s.eligible_expenses]);
  renderList($('#detailIneligibleExpenses'), Array.isArray(s.ineligible_or_unclear) ? s.ineligible_or_unclear : [s.ineligible_or_unclear]);
  renderList($('#detailRequiredDocuments'), Array.isArray(s.required_documents) ? s.required_documents : [s.required_documents]);
  renderList($('#detailNextActions'), Array.isArray(s.application_steps) ? s.application_steps : [s.application_steps]);

  const exp = s.expert_needed || {};
  renderTags($('#detailExpertTypes'), exp.types);
  const expNote = $('#detailExpertNote');
  if (expNote) {
    expNote.textContent = exp.label || '必要に応じて専門家への相談を検討してください。';
  }

  document.title = `${data.title || '応募判断詳細'}｜応募判断詳細`;
}

async function loadAndRender() {
  const id = getQueryId();
  if (!id) {
    stopLoading();
    $('#detailTitle').textContent = 'IDが指定されていません';
    $('#detailEyebrow').textContent = 'エラー';
    $('#detailCatch').textContent = '一覧ページから公募を選択してください。';
    return;
  }
  startLoading();
  renderShellFromItem(cachedSearchItem(id));
  try {
    const quick = await api('/api/grant?id=' + encodeURIComponent(id));
    renderShellFromItem(quick.item);
  } catch (_) {}
  try {
    const data = await api('/api/grant-summary?id=' + encodeURIComponent(id));
    render(data);
    stopLoading();
  } catch (err) {
    stopLoading();
    $('#detailTitle').textContent = '情報の取得に失敗しました';
    $('#detailEyebrow').textContent = 'エラー';
    $('#detailCatch').textContent = err && err.message ? err.message : '時間を置いて再度お試しください。';
  }
}

// --- リード送信（既存 index.html と同等の最小実装） ---
function openLead(type, item = {}) {
  const copy = {
    consultation:     ['専門家に相談する', 'この公募や応募準備について相談したい内容を送ってください。'],
    feedback:         ['β版へのご意見', 'ご意見・ご要望をお聞かせください。'],
    automation_pack:  ['自動化したい', '自動化に向けたご要望をお聞かせください。'],
    expert_listing:   ['専門家として掲載', '掲載希望の内容をお聞かせください。'],
  }[type] || ['お問い合わせ', 'お問い合わせ内容をお送りください。'];
  $('#leadTitle').textContent = copy[0];
  $('#leadDescription').textContent = copy[1];
  $('#leadStatus').textContent = '';
  const f = $('#leadForm'); f.reset();
  f.lead_type.value = type;
  f.grant_id.value = item.id || getQueryId() || '';
  f.grant_title.value = item.title || ($('#detailTitle') && $('#detailTitle').textContent) || '';
  if (f.grant_title.value && !f.message.value) {
    f.message.value = `「${f.grant_title.value}」について相談したいです。`;
  }
  $('#leadDialog').showModal();
}

async function submitLead(e) {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target).entries());
  data.source_page = location.pathname;
  try {
    const res = await fetch('/api/lead', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    if (!res.ok) throw new Error('送信に失敗しました');
    $('#leadStatus').textContent = '送信しました。担当者よりご連絡します。';
    setTimeout(() => $('#leadDialog').close(), 1200);
  } catch (err) {
    $('#leadStatus').textContent = err.message || '送信に失敗しました';
  }
}

document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-lead-type]');
  if (btn) {
    e.preventDefault();
    openLead(btn.dataset.leadType, {});
    return;
  }
  if (e.target.closest('[data-dialog-close]')) {
    $('#leadDialog').close();
  }
});
document.addEventListener('submit', (e) => {
  if (e.target && e.target.id === 'leadForm') submitLead(e);
});

loadAndRender();
