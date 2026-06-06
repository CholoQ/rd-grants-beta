const $ = (sel, root=document) => root.querySelector(sel);
const $$ = (sel, root=document) => Array.from(root.querySelectorAll(sel));
const watchKey = 'rdFundingWatchlist:v1';
const searchStateKey = 'rdFundingSearchState:v1';
const analyticsVisitorKey = 'rikoNaviVisitor:v1';
let lastItems = [];

const leadCopy = {
  consultation: ['専門家に相談する', 'この公募や応募準備について相談したい内容を送ってください。'],
  automation_pack: ['公募ウォッチ自動化パック相談', '自社テーマに合う公募収集・要約・通知を自動化したい内容を送ってください。'],
  expert_listing: ['専門家掲載希望', '対応分野、地域、支援内容、掲載希望を送ってください。'],
  feedback: ['β版フィードバック', '使ってみた感想や改善点を送ってください。'],
};

function getWatchlist(){ try{return JSON.parse(localStorage.getItem(watchKey)||'[]')}catch{return[]} }
function setWatchlist(items){ localStorage.setItem(watchKey, JSON.stringify(items.slice(0,50))); }
function addWatch(item){
  const list = getWatchlist();
  if(!list.some(x => String(x.id) === String(item.id))){
    list.unshift({id:item.id,title:item.title,institution_name:item.institution_name,match_score:item.match_score,status:item.status});
    setWatchlist(list);
  }
}
function removeWatch(id){ setWatchlist(getWatchlist().filter(x => String(x.id)!==String(id))); }

function saveSearchState(items, metaText, params) {
  try {
    localStorage.setItem(searchStateKey, JSON.stringify({
      items: (items || []).slice(0, 20),
      metaText: metaText || '',
      params: params || null,
      savedAt: Date.now(),
    }));
  } catch (_) {}
}

function getSearchState() {
  try {
    const state = JSON.parse(localStorage.getItem(searchStateKey) || 'null');
    if (!state || !Array.isArray(state.items) || !state.items.length) return null;
    if (Date.now() - Number(state.savedAt || 0) > 24 * 60 * 60 * 1000) return null;
    return state;
  } catch (_) {
    return null;
  }
}

function clearSearchState() {
  try { localStorage.removeItem(searchStateKey); } catch (_) {}
}

function restoreSearchState() {
  const state = getSearchState();
  if (!state) return;
  lastItems = state.items || [];
  $('#resultMeta').textContent = state.metaText || `${lastItems.length}件の候補を表示中。`;
  renderItems(lastItems);
}

async function api(path, options={}){
  const res = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
  const data = await res.json().catch(()=>({}));
  if(!res.ok) throw new Error(data.error || 'API error');
  return data;
}

function getAnalyticsVisitorId() {
  try {
    let id = localStorage.getItem(analyticsVisitorKey);
    if (!id) {
      id = (window.crypto && window.crypto.randomUUID) ? window.crypto.randomUUID() : `v-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      localStorage.setItem(analyticsVisitorKey, id);
    }
    return id;
  } catch (_) {
    return '';
  }
}

function trackEvent(eventType, payload={}) {
  try {
    fetch('/api/track', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        event_type: eventType,
        path: `${location.pathname}${location.hash || ''}`,
        visitor_id: getAnalyticsVisitorId(),
        payload,
      }),
      keepalive: true,
    }).catch(() => {});
  } catch (_) {}
}

function fillSelect(id, options){
  const el = $('#'+id); if(!el) return;
  el.innerHTML = (options||[]).map(o => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`).join('');
}
function escapeHtml(v){ return String(v ?? '').replace(/[&<>"]/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[s])); }

function getSummarySourceLabel(src) {
  return {gemini: 'Gemini', cache: 'キャッシュ', rule_based: 'ルールベース'}[src] || '不明';
}

function getArr(obj, ...keys) {
  for (const k of keys) {
    const v = obj[k];
    if (v !== undefined && v !== null) return Array.isArray(v) ? v : [String(v)];
  }
  return [];
}

const RD_PHASE_LABELS = {
  idea:              'アイデア・シーズ探索',
  poc:               'PoC・概念実証',
  prototype:         '試作・開発',
  demonstration:     '実証・社会実装前',
  commercialization: '事業化・量産前',
};

function formatDeadline(val) {
  if (!val || val === '要確認') return '';
  const m = val.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (m) return `締切：${m[1]}年${parseInt(m[2])}月${parseInt(m[3])}日`;
  return val;
}

function parseBudget(val) {
  if (!val || val === '要確認') return [];
  const out = [];
  const rawYen = val.match(/([\d,]+)円/);
  if (rawYen) {
    const n = parseInt(rawYen[1].replace(/,/g, ''), 10);
    if (!isNaN(n)) {
      const prefix = /(上限|最大|補助上限)/.test(val) ? '上限：' : '';
      out.push(prefix + formatYen(n));
    }
  }
  const rate = val.match(/(\d+)\s*[\/／]\s*(\d+)\s*(以内|以下)?/);
  if (rate) out.push(`補助率：${rate[1]}/${rate[2]}${rate[3] || '以内'}`);
  if (!out.length) out.push(val);
  return out;
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

function officialUrlForItem(item) {
  return item.safe_public_url || item.official_url || item.front_subsidy_detail_page_url || '';
}

function splitTextList(values) {
  return (values || [])
    .flatMap(v => String(v || '').split(' / '))
    .map(v => v.trim())
    .filter(Boolean);
}

function uniqText(values) {
  const seen = new Set();
  const out = [];
  values.forEach(v => {
    const text = String(v || '').trim();
    if (!text || seen.has(text)) return;
    seen.add(text);
    out.push(text);
  });
  return out;
}

function textHasAny(text, terms) {
  const hay = String(text || '').toLowerCase();
  return terms.some(term => hay.includes(String(term).toLowerCase()));
}

function estimateJudgementFromItem(item) {
  const score = getItemScore(item);
  const cautions = splitTextList(item.match_cautions || []);
  const titleText = [
    item.title, item.granttype, item.system_name, item.institution_name,
    item.detail_plain, item.subsidy_catch_phrase, cautions.join(' '),
  ].join(' ');
  const status = String(item.status || '').toLowerCase();

  let riskLevel = 'low';
  if (status === 'closed' || (score !== null && score < 40) || textHasAny(titleText, ['対象外', '地域不一致', '締切済み'])) {
    riskLevel = 'high';
  } else if (
    status === 'unknown' || status === 'upcoming' ||
    cautions.length || (score !== null && score < 70) ||
    textHasAny(titleText, ['要確認', '企業単独', '大学・研究者経由'])
  ) {
    riskLevel = 'medium';
  }
  const riskLabel = riskLevel === 'high' ? '高' : (riskLevel === 'medium' ? '中' : '低');
  const riskCls = riskLevel === 'high' ? 'high' : (riskLevel === 'medium' ? 'mid' : 'low');

  let diffScore = 2;
  const maxLimit = Number(item.subsidy_max_limit || 0);
  if (maxLimit >= 100000000) diffScore += 2;
  else if (maxLimit >= 30000000) diffScore += 1;
  if (textHasAny(titleText, ['NEDO', 'SBIR', 'AMED', 'GAPファンド', '委託', 'コンソーシアム', '共同', '大学・研究者経由'])) diffScore += 1;
  if (cautions.length >= 3) diffScore += 1;
  if (status === 'unknown') diffScore += 1;
  diffScore = Math.max(1, Math.min(5, diffScore));
  const diffLabel = ({1:'低', 2:'やや低', 3:'中', 4:'やや高', 5:'高'})[diffScore] || '中';

  const prepMap = {
    1: {label:'1〜2週間', cls:'short'},
    2: {label:'2〜3週間', cls:'short'},
    3: {label:'3〜5週間', cls:'mid'},
    4: {label:'1〜2か月', cls:'long'},
    5: {label:'2か月以上', cls:'long'},
  };
  const prep = prepMap[diffScore] || prepMap[3];

  let expertLevel = 'optional';
  if (diffScore >= 5 || riskLevel === 'high' || textHasAny(titleText, ['大学・研究者経由', '企業単独', 'AMED', 'NEDO', 'SBIR', 'GAPファンド'])) {
    expertLevel = diffScore >= 5 || riskLevel === 'high' ? 'high' : 'recommended';
  } else if (diffScore >= 3 || cautions.length) {
    expertLevel = 'recommended';
  }

  return {
    exclusion_risks: [{label: riskLabel, level: riskLevel}],
    difficulty: {score: diffScore, label: diffLabel},
    prep_load: {label: prep.label, cls: prep.cls},
    expert_needed: {level: expertLevel},
  };
}

function judgementBadgesHtml(item) {
  const j = estimateJudgementFromItem(item);
  const risk = summarizeRiskLevel(j.exclusion_risks);
  const diff = j.difficulty || {};
  const prep = j.prep_load || {};
  const expert = j.expert_needed || {};
  return `
    <div class="judgement-badges" data-role="judgement-badges">
      <span class="j-badge j-badge--risk j-badge--risk-${escapeHtml(risk.cls)}" data-j="risk">🚫 対象外リスク：${escapeHtml(risk.label)}</span>
      <span class="j-badge j-badge--diff j-badge--diff-s${escapeHtml(diff.score || 'unknown')}" data-j="diff">🪜 申請難易度：${escapeHtml(diff.label || '要確認')}</span>
      <span class="j-badge j-badge--prep j-badge--prep-${escapeHtml(prep.cls || 'unknown')}" data-j="prep">⏳ 準備期間：${escapeHtml(prep.label || '要確認')}</span>
      <span class="j-badge j-badge--expert j-badge--expert-${escapeHtml(expert.level || 'unknown')}" data-j="expert">🙋 専門家相談：${escapeHtml(expertLevelLabel(expert.level))}</span>
    </div>
  `;
}

function updateJudgementBadges(card, data) {
  if (!card || !data) return;
  const s = (data && data.summary) ? data.summary : data;
  const risk = summarizeRiskLevel(s.exclusion_risks);
  const diff = s.difficulty || {};
  const prep = s.prep_load || {};
  const expert = s.expert_needed || {};
  const setText = (key, text, cls) => {
    const el = card.querySelector(`[data-j="${key}"]`);
    if (!el) return;
    el.textContent = text;
    if (cls) el.className = `j-badge j-badge--${key} j-badge--${key}-${cls}`;
  };
  setText('risk', `🚫 対象外リスク：${risk.label}`, risk.cls);
  setText('diff', `🪜 申請難易度：${diff.label || '要確認'}`, diff.score ? `s${diff.score}` : 'unknown');
  setText('prep', `⏳ 準備期間：${prep.label || '要確認'}`, prep.cls || 'unknown');
  setText('expert', `🙋 専門家相談：${expertLevelLabel(expert.level)}`, expert.level || 'unknown');
}

function renderSummaryHtml(data) {
  const s = data.summary || data;
  const srcLabel = getSummarySourceLabel(data.summary_source || s.summary_source);

  function isUnknownValue(val) {
    const text = String(val ?? '').trim();
    return !text || text === '要確認' || text === 'unknown';
  }

  function toItems(value) {
    const raw = Array.isArray(value) ? value : [value];
    const items = raw.map(v => String(v ?? '').trim()).filter(Boolean);
    return items.length ? items : ['要確認'];
  }

  function row(label, value) {
    const items = toItems(value);
    const isUnknown = items.length === 1 && isUnknownValue(items[0]);
    const listClass = isUnknown ? ' class="sum-unknown"' : '';
    const displayItems = isUnknown ? ['要確認'] : items;
    return `<div class="sum-row"><span class="sum-label">${escapeHtml(label)}</span><ul${listClass}>${displayItems.map(v => `<li>${escapeHtml(v)}</li>`).join('')}</ul></div>`;
  }

  const phaseLabel = RD_PHASE_LABELS[s.rd_phase] || '';
  const deadlineText = formatDeadline(s.deadline) || s.deadline;

  return [
    `<div class="sum-source">生成元: ${escapeHtml(srcLabel)}</div>`,
    row('概要', s.overview),
    row('目的', s.purpose),
    row('研究フェーズ', phaseLabel || s.rd_phase),
    row('分野', getArr(s, 'fields')),
    row('予算', parseBudget(s.budget)),
    row('締切', deadlineText),
    row('こんな会社に合いそう', getArr(s, 'suitable_for')),
    row('合わないかもしれない会社', getArr(s, 'not_suitable_for')),
    row('誰が応募できる？', getArr(s, 'target_companies', 'target_conditions')),
    row('何に使えるお金？', getArr(s, 'eligible_expenses')),
    row('用意するもの', getArr(s, 'required_documents')),
    row('まずやること', getArr(s, 'preparation_tasks', 'application_steps')),
    row('相談するならこの人', getArr(s, 'expert_type_needed')),
    row('確認しておきたいこと', getArr(s, 'first_questions_to_ask')),
    row('気をつけること', getArr(s, 'cautions')),
  ].join('');
}

async function initMeta(){
  try{
    const data = await api('/api/rd-meta');
    const m = data.meta || {};
    fillSelect('rd_phase', m.rd_phases);
    fillSelect('tech_domain', m.tech_domains);
    fillSelect('support_type', m.support_types);
    fillSelect('budget_range', m.budget_ranges);
  }catch(e){ $('#resultMeta').textContent = '選択肢の取得に失敗しました: '+e.message; }
}

function formPayload(form){
  const fd = new FormData(form);
  return {
    rd_phase: fd.get('rd_phase') || '',
    tech_domain: fd.get('tech_domain') || '',
    support_type: fd.get('support_type') || 'any',
    budget_range: fd.get('budget_range') || '',
    region_text: fd.get('region_text') || '',
    free_text: fd.get('free_text') || '',
    sources: fd.getAll('sources'),
    fast_mode: true,
  };
}

function formatYen(n) {
  if (n >= 100000000) return `${n / 100000000}億円`;
  if (n >= 10000) return `${(n / 10000).toLocaleString()}万円`;
  return `${n.toLocaleString()}円`;
}

function humanizeReason(r) {
  const exact = {
    '研究開発用途に合う':         '研究開発に使える可能性があります',
    '全国対象':                   '全国から応募できます',
    '従業員数指定なし':           '会社規模の条件は比較的ゆるそうです',
    'スタートアップ向け文脈あり': 'スタートアップにも合いそうです',
    '現在募集中':                 '現在応募できます',
  };
  if (exact[r]) return exact[r];
  if (r.startsWith('対象経費一致:')) return '研究・開発費に使える可能性があります';
  const budget = r.match(/補助上限\s*([\d,]+)円/);
  if (budget) return `最大${formatYen(parseInt(budget[1].replace(/,/g, ''), 10))}まで使える可能性があります`;
  const region = r.match(/^(.+?)\s*対象$/);
  if (region) return `${region[1]}の事業者が対象となる可能性があります`;
  return r;
}

function getItemScore(item) {
  const raw = item.match_score ?? item.fit_percent;
  const n = Number(raw);
  if (!Number.isFinite(n)) return null;
  return Math.max(0, Math.min(100, Math.round(n)));
}

function scoreBand(score) {
  if (score === null) {
    return {
      tone: 'unknown',
      label: '要確認',
      guide: '条件が読み取りきれていない候補です。公式情報で対象条件を確認してください。',
      color: '#8a7a70',
    };
  }
  if (score >= 90) return {tone: 'excellent', label: 'かなり有望', guide: '応募できる可能性が高い候補です。締切と対象経費をすぐ確認したいです。', color: '#248a5a'};
  if (score >= 80) return {tone: 'high', label: '応募候補', guide: '応募を前向きに検討できる候補です。要件の細部を見にいきましょう。', color: '#2f9a72'};
  if (score >= 70) return {tone: 'good', label: '要件確認', guide: 'かなり近いですが、企業対象・対象経費・フェーズの確認が必要です。', color: '#6aa84f'};
  if (score >= 60) return {tone: 'mid', label: '可能性あり', guide: '使える可能性はあります。ズレている条件がないか慎重に見たい候補です。', color: '#d19a2e'};
  if (score >= 50) return {tone: 'watch', label: '注意して検討', guide: '参考候補です。条件が一部合わない可能性があります。', color: '#d9822b'};
  if (score >= 40) return {tone: 'low', label: '参考候補', guide: '制度の方向性は近いかもしれませんが、応募候補としては弱めです。', color: '#c86143'};
  if (score >= 30) return {tone: 'far', label: '遠い', guide: '条件との距離が大きい候補です。見るなら参考程度です。', color: '#b94a48'};
  if (score >= 20) return {tone: 'very-low', label: 'かなり遠い', guide: '応募対象から外れる可能性が高い候補です。', color: '#9f3f46'};
  return {tone: 'bad', label: '対象外寄り', guide: '今回の条件では応募候補にしにくいです。', color: '#7f3842'};
}

function scoreText(item) {
  const score = getItemScore(item);
  const band = scoreBand(score);
  return score === null ? `一致度 ${band.label}` : `一致度 ${score}%・${band.label}`;
}

function statusLabel(status) {
  const raw = String(status || '').toLowerCase();
  if (raw === 'open') return '募集中';
  if (raw === 'upcoming') return '募集前';
  if (raw === 'closed') return '締切済み';
  return '募集時期 要確認';
}

function sourceMixText(counts) {
  return `Jグランツ ${counts.jgrants_items||0} / NEDO ${counts.nedo_items||0} / JST ${counts.jst_items||0} / AMED ${counts.amed_items||0} / アクセラ・GAP ${counts.accelerator_items||0}`;
}

function scoreGuideHtml(item) {
  const score = getItemScore(item);
  const band = scoreBand(score);
  const width = score === null ? 8 : score;
  return `
    <div class="score-guide" aria-label="一致度の目安">
      <div class="score-guide__bar"><span class="score-guide__fill" style="width:${width}%;background:${band.color}"></span></div>
      <div class="score-guide__text">${escapeHtml(band.guide)}</div>
    </div>
  `;
}

function resultSummaryText(item) {
  const score = getItemScore(item);
  const band = scoreBand(score);
  if (score !== null && score < 60) return band.guide;
  return item.match_summary || item.detail_plain || item.subsidy_catch_phrase || '詳細は公式ページを確認してください。';
}

function importantChecksForItem(item) {
  const checks = splitTextList(item.match_cautions || []);
  const score = getItemScore(item);
  const status = String(item.status || '').toLowerCase();
  if (status === 'upcoming') checks.push('募集開始前、または次回募集待ちの可能性があります');
  if (status === 'unknown') checks.push('募集状況と締切を公式ページで確認してください');
  if (!officialUrlForItem(item)) checks.push('公式ページへのリンクが未確認です');
  if (score !== null && score < 60) checks.push(scoreBand(score).guide);
  if (score !== null && score >= 60 && score < 78) checks.push('企業対象・対象経費・フェーズの3点を先に確認してください');
  return uniqText(checks).slice(0, 5);
}

function renderChecksHtml(item) {
  const checks = importantChecksForItem(item);
  if (!checks.length) return '';
  return `
    <div class="match-cautions">
      <p class="match-cautions-head">確認事項</p>
      <ul>${checks.map(v => `<li>${escapeHtml(v)}</li>`).join('')}</ul>
    </div>
  `;
}

const CLIENT_NEGATIVE_SECTOR_TERMS = {
  medical: ['医療', '医療機関', '病院', '小児科', '診療', '臨床', '患者', '医療dx', '医療ＤＸ', '医療DX', '診断', '治療', 'medical', 'hospital', 'clinical'],
  drug_discovery: ['創薬', '医薬', '医薬品', '薬剤', 'drug discovery', 'pharma', 'pharmaceutical'],
};

function applyClientResultGuards(items, params={}) {
  const negativeSectors = new Set(params.negative_sectors || []);
  if (!negativeSectors.size) return items || [];
  return (items || []).filter(item => {
    const text = [
      item.title, item.institution_name, item.system_name, item.subsidy_catch_phrase,
      item.detail_plain, item.detail, item.match_summary, item.granttype,
    ].map(v => String(v || '').toLowerCase()).join(' ');
    for (const sector of negativeSectors) {
      const terms = CLIENT_NEGATIVE_SECTOR_TERMS[sector] || [];
      if (terms.some(term => text.includes(term.toLowerCase()))) return false;
    }
    return true;
  });
}

function renderItems(items) {
  const root = $('#results');
  if (!items.length) {
    root.innerHTML = '<div class="result-card">厳しめに見ると候補が見つかりませんでした。予算帯を広げるか、自由記述で技術内容を少し詳しく入れてください。</div>';
    return;
  }
  const INITIAL_LIMIT = 5;
  function renderCards(list) {
    return list.map(item => {
      const officialUrl = officialUrlForItem(item);
      const score = getItemScore(item);
      const band = scoreBand(score);
      return `
      <article class="result-card" data-id="${escapeHtml(item.id)}">
        <h3>${escapeHtml(item.title)}</h3>
        <div class="meta">
          <span class="pill">${escapeHtml(item.institution_name || item.system_name || item.source || '制度')}</span>
          <span class="pill pill--score score-pill score-pill--${escapeHtml(band.tone)}">${escapeHtml(scoreText(item))}</span>
          <span class="pill">${escapeHtml(statusLabel(item.status))}</span>
          <span class="pill">${escapeHtml(item.budget_scale_label || '')}</span>
        </div>
        ${scoreGuideHtml(item)}
        ${judgementBadgesHtml(item)}
        <p>${escapeHtml(resultSummaryText(item))}</p>
        ${(item.match_reasons||[]).length ? `<div class="match-reasons"><p class="match-reasons-head">なぜおすすめ？</p><ul>${(item.match_reasons||[]).flatMap(r=>r.split(' / ')).slice(0,5).map(r=>`<li>${escapeHtml(humanizeReason(r))}</li>`).join('')}</ul></div>` : ''}
        ${renderChecksHtml(item)}
        <div class="result-actions">
          <a class="button button--small button--primary-warm" data-detail-link href="/detail.html?id=${encodeURIComponent(item.id)}">応募判断の詳細を見る</a>
          <button class="button button--small" data-action="summary">やさしく読む</button>
          <button class="button button--small" data-action="watch">ウォッチに保存</button>
          <button class="button button--small" data-action="consult">専門家に相談</button>
          ${officialUrl ? `<a class="button button--small" href="${escapeHtml(officialUrl)}" rel="noopener">公式ページ</a>` : ''}
        </div>
        <div class="details" hidden></div>
      </article>
    `}).join('');
  }
  root.innerHTML = renderCards(items.slice(0, INITIAL_LIMIT));
  if (items.length > INITIAL_LIMIT) {
    const footer = document.createElement('div');
    footer.className = 'result-more-footer';
    footer.innerHTML = `<span class="result-more-count">全${items.length}件中 ${INITIAL_LIMIT}件を表示中</span><button class="button button--small result-more-btn">さらに ${items.length - INITIAL_LIMIT}件を表示</button>`;
    footer.querySelector('.result-more-btn').addEventListener('click', () => { root.innerHTML = renderCards(items); });
    root.appendChild(footer);
  }
}

async function search(e){
  e.preventDefault();
  $('#resultMeta').textContent = '検索中です...';
  $('#results').innerHTML = '';
  try{
    const payload = formPayload(e.target);
    trackEvent('search_submitted', {mode: 'form', sources: (payload.sources || []).join(',')});
    const data = await api('/api/rd-search', {method:'POST', body:JSON.stringify(payload)});
    lastItems = applyClientResultGuards(data.items || [], payload);
    const counts = data.source_mix || data.source_counts || {};
    $('#resultMeta').textContent = `${lastItems.length}件の候補を表示中。${sourceMixText(counts)}`;
    trackEvent('search_results', {mode: 'form', result_count: String(lastItems.length)});
    saveSearchState(lastItems, $('#resultMeta').textContent, payload);
    renderItems(lastItems);
  }catch(err){ $('#resultMeta').textContent = '検索に失敗しました: '+err.message; }
}

async function onResultClick(e){
  const btn = e.target.closest('button[data-action]'); if(!btn) return;
  const card = e.target.closest('.result-card');
  const id = card.dataset.id;
  const item = lastItems.find(x => String(x.id)===String(id)) || getWatchlist().find(x => String(x.id)===String(id));
  if(btn.dataset.action === 'watch'){
    trackEvent('watch_saved', {item_id: id});
    addWatch(item); btn.textContent = '保存しました'; return;
  }
  if(btn.dataset.action === 'consult'){
    trackEvent('consult_opened', {item_id: id});
    openLead('consultation', item); return;
  }
  if(btn.dataset.action === 'summary'){
    trackEvent('summary_opened', {item_id: id});
    const box = $('.details', card); box.hidden = false; box.textContent = '要点を取得中です...';
    try{
      const data = await api('/api/grant-summary?id='+encodeURIComponent(id));
      box.innerHTML = renderSummaryHtml(data);
      updateJudgementBadges(card, data);
    }catch(err){ box.textContent = '要約取得に失敗しました: '+err.message; }
  }
}

function renderWatchlist(){
  const items = getWatchlist();
  $('#resultMeta').textContent = `ウォッチリスト ${items.length}件`;
  $('#results').innerHTML = items.length ? items.map(item => {
    const band = scoreBand(getItemScore(item));
    return `
    <article class="result-card" data-id="${escapeHtml(item.id)}">
      <h3>${escapeHtml(item.title)}</h3>
      <div class="meta"><span class="pill">${escapeHtml(item.institution_name||'保存済み')}</span><span class="pill pill--score score-pill score-pill--${escapeHtml(band.tone)}">${escapeHtml(scoreText(item))}</span></div>
      <div class="result-actions">
        <button class="button button--small" data-action="summary">やさしく読む</button>
        <button class="button button--small" onclick="removeWatch('${escapeHtml(item.id)}'); renderWatchlist();">削除</button>
        <button class="button button--small" data-action="consult">専門家に相談</button>
      </div>
      <div class="details" hidden></div>
    </article>`;
  }).join('') : '<div class="result-card">まだ保存された公募はありません。</div>';
}

async function runBulk(path){
  const ids = getWatchlist().map(x => x.id).slice(0,10);
  if(!ids.length){ $('#sideOutput').textContent = '先に公募をウォッチリストに保存してください。'; return; }
  $('#sideOutput').textContent = '作成中です...';
  try{
    const data = await api(path, {method:'POST', body:JSON.stringify({ids})});
    $('#sideOutput').textContent = JSON.stringify(data, null, 2);
  }catch(err){ $('#sideOutput').textContent = '取得に失敗しました: '+err.message; }
}

function openLead(type, item={}){
  const [title, desc] = leadCopy[type] || leadCopy.consultation;
  $('#leadTitle').textContent = title; $('#leadDescription').textContent = desc; $('#leadStatus').textContent = '';
  const f = $('#leadForm'); f.reset();
  f.lead_type.value = type; f.grant_id.value = item.id || ''; f.grant_title.value = item.title || '';
  if(item.title && !f.message.value) f.message.value = `「${item.title}」について相談したいです。`;
  $('#leadDialog').showModal();
}

async function submitLead(e){
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target).entries());
  data.source_page = location.pathname;
  $('#leadStatus').textContent = '送信中です...';
  try{
    const res = await api('/api/lead', {method:'POST', body:JSON.stringify(data)});
    $('#leadStatus').textContent = res.message || '送信しました。';
    setTimeout(()=>$('#leadDialog').close(), 900);
  }catch(err){ $('#leadStatus').textContent = '送信に失敗しました: '+err.message; }
}

// ============ CHAT STATE MACHINE ============

const FALLBACK_OPTIONS = {
  rd_phase: [
    {value:'idea',             label:'アイデア・シーズ探索'},
    {value:'poc',              label:'PoC・概念実証'},
    {value:'prototype',        label:'試作・開発'},
    {value:'demonstration',    label:'実証・社会実装前'},
    {value:'commercialization',label:'事業化・量産前'},
  ],
  tech_domain: [
    {value:'ai',           label:'AI・ソフトウェア'},
    {value:'medical',      label:'医療・医療機器'},
    {value:'bio',          label:'バイオ・創薬'},
    {value:'healthcare',   label:'ヘルスケア'},
    {value:'energy',       label:'エネルギー・GX'},
    {value:'materials',    label:'材料・化学'},
    {value:'robotics',     label:'ロボティクス・製造'},
    {value:'agri',         label:'アグリテック'},
    {value:'semiconductor',label:'半導体・電子'},
    {value:'other',        label:'その他'},
  ],
  support_type: [
    {value:'development', label:'研究・試作を進めたい'},
    {value:'validation',  label:'PoC・実証を進めたい'},
    {value:'equipment',   label:'設備導入も含めたい'},
    {value:'startup',     label:'スタートアップ向けを優先'},
    {value:'grant_only',  label:'補助金・助成金を優先'},
    {value:'accelerator', label:'アクセラ・自治体実証も見たい'},
    {value:'activity_fund', label:'活動資金・協業費も見たい'},
    {value:'gap_fund', label:'GAPファンドも見たい'},
    {value:'deeptech_startup', label:'NEDO・SBIR系も見たい'},
    {value:'municipality_poc', label:'自治体PoC・実証も見たい'},
    {value:'ip',          label:'知財・特許を取りたい'},
  ],
  budget_range: [
    {value:'under5m',  label:'500万円未満'},
    {value:'5m_30m',   label:'500万〜3000万円'},
    {value:'30m_100m', label:'3000万〜1億円'},
    {value:'over100m', label:'1億円以上'},
  ],
};

const REGION_OPTIONS = [
  {value:'全国',   label:'全国・場所不問'},
  {value:'東京都', label:'東京・首都圏'},
  {value:'大阪府', label:'大阪・関西'},
  {value:'愛知県', label:'東海・中部'},
  {value:'福岡県', label:'九州・沖縄'},
];

const STEPS = [
  {key:'rd_phase',    metaKey:'rd_phases',       question:'まずは今の研究開発の段階を教えてください。',  placeholder:'例：PoC段階、試作を終えたところ'},
  {key:'tech_domain', metaKey:'tech_domains',    question:'どんな技術・分野のテーマですか？近いものを選んでください。',           placeholder:'例：AIを使った医療診断ツール'},
  {key:'support_type',metaKey:'support_types',   question:'今いちばん助けてほしいことはどれに近いですか？',       placeholder:'例：試作費用を補助してほしい'},
  {key:'budget_range',metaKey:'budget_ranges',   question:'希望する資金規模は、ざっくりどのくらいですか？',   placeholder:'例：1000万円程度、大きいほど良い'},
  {key:'region_text', staticOptions:REGION_OPTIONS, question:'事業拠点の地域も見ておきます。近い地域を選んでください。',    placeholder:'例：神奈川県横浜市、北海道'},
  {key:'free_text', isFinal:true, skipLabel:'このまま検索する',
   question:'最後に、りこに伝えておきたい補足があればどうぞ。（任意）',
   placeholder:'例：大学発スタートアップで試作費と人件費に使える補助金を探しています。'},
];

const MAIN_STEP_COUNT = STEPS.filter(s => !s.isFinal).length; // 5

let chatMeta = {};
let chatParams = {};
let chatStep = 0;
let chatFreeNotes = [];
let proposedPayload = null;

function beginDirectConversation() {
  freezeChips();
  $('#chatMessages').innerHTML = '';
  $('#chatInput').hidden = true;
  const progress = $('#chatProgress');
  if (progress) progress.textContent = '';
}

function resetChatState() {
  chatParams = {
    rd_phase: '', tech_domain: '', support_type: 'any',
    budget_range: '', region_text: '', free_text: '',
    sources: ['jgrants', 'nedo', 'jst', 'amed', 'accelerators'],
    fast_mode: true,
  };
  chatStep = 0;
  chatFreeNotes = [];
  proposedPayload = null;
}

function getChipOptions(step) {
  if (step.staticOptions) return step.staticOptions;
  const fromMeta = step.metaKey && chatMeta[step.metaKey];
  if (fromMeta) return fromMeta.filter(o => o.value !== '');
  return FALLBACK_OPTIONS[step.key] || [];
}

function stepChoiceHint(step) {
  if (step.isFinal) return '補足がなければ、このまま検索できます。';
  return '近いものを選んでください。なければ下に書けます。';
}

function stepInputHint(step) {
  if (step.isFinal) return '補足があれば入力してください。';
  return '選択肢にないときだけ入力してください。';
}

function appendChatMsg(role, text, chips, hint) {
  const container = $('#chatMessages');
  const msg = document.createElement('div');
  msg.className = `chat-msg chat-msg--${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  bubble.textContent = text;
  msg.appendChild(bubble);
  if (chips && chips.length) {
    if (hint) {
      const help = document.createElement('p');
      help.className = 'chat-choice-hint';
      help.textContent = hint;
      msg.appendChild(help);
    }
    const row = document.createElement('div');
    row.className = 'chat-chips';
    chips.forEach(opt => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chip-btn' + (opt.skip ? ' chip-btn--skip' : '');
      btn.textContent = opt.label;
      btn.dataset.value = opt.value;
      row.appendChild(btn);
    });
    msg.appendChild(row);
  }
  container.appendChild(msg);
  container.scrollTop = container.scrollHeight;
}

function freezeChips() {
  $$('.chip-btn:not(:disabled)', $('#chatMessages')).forEach(b => { b.disabled = true; });
}

function updateProgress() {
  const el = $('#chatProgress');
  if (!el) return;
  if (chatStep >= MAIN_STEP_COUNT) { el.textContent = ''; return; }
  el.textContent = `ステップ ${chatStep + 1} / ${MAIN_STEP_COUNT}`;
}

function showChatStep() {
  const step = STEPS[chatStep];
  if (!step) return;
  updateProgress();
  const options = step.isFinal ? [] : getChipOptions(step);
  const chips = [
    ...options,
    step.isFinal
      ? {value: '__skip__', label: step.skipLabel, skip: true}
      : {value: '__skip__', label: 'スキップ', skip: true},
  ];
  appendChatMsg('bot', step.question, chips, stepChoiceHint(step));
  const input = $('#chatTextInput');
  const hint = $('#chatInputHint');
  if (hint) hint.textContent = stepInputHint(step);
  input.placeholder = step.placeholder || '自由に入力...';
  $('#chatInput').hidden = false;
}

function advanceChatStep() {
  chatStep++;
  if (chatStep >= STEPS.length) { startChatSearch(); }
  else { setTimeout(showChatStep, 380); }
}

function answerChatStep(value, label) {
  const step = STEPS[chatStep];
  freezeChips();
  if (value === '__skip__') {
    appendChatMsg('user', label || 'スキップ');
  } else {
    appendChatMsg('user', label || value);
    chatParams[step.key] = value;
  }
  advanceChatStep();
}

function handleChatFreeInput(text) {
  const step = STEPS[chatStep];
  if (step.isFinal) { answerChatStep(text, text); return; }
  const matched = getChipOptions(step).find(o =>
    o.label === text || o.value === text ||
    o.label.includes(text) || text.includes(o.label)
  );
  if (matched) { answerChatStep(matched.value, matched.label); return; }
  chatFreeNotes.push(text);
  freezeChips();
  appendChatMsg('user', text);
  setTimeout(() => { appendChatMsg('bot', '承知しました。'); advanceChatStep(); }, 320);
}

async function startChatSearch() {
  updateProgress();
  $('#chatInput').hidden = true;
  if (chatFreeNotes.length) {
    chatParams.free_text = [chatParams.free_text, chatFreeNotes.join(' / ')].filter(Boolean).join(' / ');
  }
  appendChatMsg('bot', '条件が整いました。りこが近い候補を探しています…');
  $('#resultMeta').textContent = '検索中です...';
  $('#results').innerHTML = '';
  setTimeout(() => document.querySelector('.layout')?.scrollIntoView({behavior: 'smooth', block: 'start'}), 500);
  try {
    trackEvent('search_submitted', {mode: 'chat', sources: (chatParams.sources || []).join(',')});
    const data = await api('/api/rd-search', {method: 'POST', body: JSON.stringify(chatParams)});
    lastItems = applyClientResultGuards(data.items || [], chatParams);
    const c = data.source_mix || data.source_counts || {};
    $('#resultMeta').textContent = `${lastItems.length}件の候補を表示中。${sourceMixText(c)}`;
    trackEvent('search_results', {mode: 'chat', result_count: String(lastItems.length)});
    saveSearchState(lastItems, $('#resultMeta').textContent, chatParams);
    renderItems(lastItems);
    appendChatMsg('bot', `${lastItems.length}件の候補が見つかりました。下に、りこが見つけた候補を並べました。`,
      [{value: '__reset__', label: '条件を変えて再検索', skip: true}]);
  } catch (err) {
    $('#resultMeta').textContent = '検索に失敗しました: ' + err.message;
    appendChatMsg('bot', 'エラーが発生しました。もう一度お試しください。',
      [{value: '__reset__', label: 'やり直す', skip: true}]);
  }
}

function useDirectPayload(payload, message, options={}) {
  if (!options.preserveChat) beginDirectConversation();
  chatParams = {
    rd_phase: '', tech_domain: '', support_type: 'any',
    budget_range: '', region_text: '', free_text: '',
    sources: ['jgrants', 'nedo', 'jst', 'amed', 'accelerators'],
    fast_mode: true,
    ...(payload || {}),
  };
  chatFreeNotes = [];
  chatStep = STEPS.length;
  if (message) appendChatMsg('user', message);
  startChatSearch();
}

async function runQuickSearch() {
  const input = $('#quickSearchText');
  const text = (input && input.value || '').trim();
  if (!text) return;
  const extracted = extractUrlAndNotes(text);
  if (extracted.url) {
    await proposeFromCompanyUrl({
      inputText: text,
      url: extracted.url,
      needText: extracted.needText,
      autoSearch: true,
    });
    return;
  }
  useDirectPayload({ free_text: text, negative_sectors: inferNegativeSectorsFromText(text) }, text);
}

function normalizeCompanyUrlInput(value) {
  const raw = (value || '').trim();
  if (!raw) return '';
  if (/^https?:\/\//i.test(raw)) return raw;
  if (/^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:\/.*)?$/.test(raw)) return `https://${raw}`;
  return raw;
}

function extractUrlAndNotes(value) {
  const raw = (value || '').trim();
  const match = raw.match(/https?:\/\/[^\s　]+|(?:www\.)?[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}(?:\/[^\s　]*)?/i);
  if (!match) return {url: '', needText: raw};
  const originalUrl = match[0];
  const cleanedUrl = originalUrl.replace(/[、。，．,.)）\]】]+$/g, '');
  const url = normalizeCompanyUrlInput(cleanedUrl);
  const needText = raw.replace(originalUrl, ' ').replace(/\s+/g, ' ').trim();
  return {url, needText};
}

function fallbackCompanyPayload(url, needText='') {
  return {
    rd_phase: '', tech_domain: '', support_type: 'development',
    budget_range: '', region_text: '', free_text: [plusLabel('会社URL', url), needText].filter(Boolean).join('\n'),
    sources: ['jgrants', 'nedo', 'jst', 'amed', 'accelerators'],
    negative_sectors: inferNegativeSectorsFromText(needText),
    fast_mode: true,
  };
}

function plusLabel(label, value) {
  return value ? `${label}: ${value}` : '';
}

function inferBudgetRangeFromText(text) {
  const normalized = String(text || '').replace(/,/g, '').toLowerCase();
  if (/\d+(?:\.\d+)?\s*(?:万|万円)?\s*[〜~～-]\s*\d+(?:\.\d+)?\s*億/.test(normalized)) return '30m_100m';
  const oku = normalized.match(/(\d+(?:\.\d+)?)\s*億/);
  if (oku) return Number(oku[1]) >= 1 ? 'over100m' : '30m_100m';
  const man = normalized.match(/(\d+(?:\.\d+)?)\s*万/);
  if (man) {
    const yen = Number(man[1]) * 10000;
    if (yen >= 100000000) return 'over100m';
    if (yen >= 30000000) return '30m_100m';
    if (yen >= 5000000) return '5m_30m';
    return 'under5m';
  }
  const yen = normalized.match(/(\d{7,})\s*(?:円|yen)?/);
  if (yen) {
    const amount = Number(yen[1]);
    if (amount >= 100000000) return 'over100m';
    if (amount >= 30000000) return '30m_100m';
    if (amount >= 5000000) return '5m_30m';
    return 'under5m';
  }
  return '';
}

function inferNegativeSectorsFromText(text) {
  const raw = String(text || '');
  const hits = [];
  if (/医療(?:系|関連|dx|DX)?(?:は|を|も)?(?:除|外|いらない|不要|避け)/.test(raw) || /病院(?:向け|関連)?(?:は|を|も)?(?:除|外|いらない|不要|避け)/.test(raw) || /(?:exclude|no|avoid)\s+(?:medical|hospital|clinical)/i.test(raw)) {
    hits.push('medical');
  }
  if (/創薬(?:は|を|も)?(?:除|外|いらない|不要|避け)/.test(raw) || /医薬(?:品)?(?:は|を|も)?(?:除|外|いらない|不要|避け)/.test(raw) || /(?:exclude|no|avoid)\s+(?:drug|pharma|drug discovery)/i.test(raw)) {
    hits.push('drug_discovery');
  }
  if (hits.includes('medical') && /ヘルスケア|healthcare|腸内環境|腸内細菌|腸内フローラ|マイクロバイオーム|microbiome|未病|予防/i.test(raw)) {
    hits.push('drug_discovery');
  }
  return Array.from(new Set(hits));
}

function refineCompanyPayloadFromSummary(payload, summary, needText='') {
  const p = {...(payload || {})};
  const text = `${summary || ''} ${p.free_text || ''} ${needText || ''}`.toLowerCase();
  const raw = `${summary || ''} ${p.free_text || ''} ${needText || ''}`;
  const agriStrong = [
    '植物', '根', '土壌', '圃場', '作物', '栽培', '農業', '農・環境',
    '食・農', '内生菌', 'エンドファイト', 'endophyte', '微生物', '共生',
  ];
  const healthcareStrong = [
    'ヘルスケア', 'healthcare', '腸内環境', '腸内細菌', '腸内フローラ', '菌叢',
    'マイクロバイオーム', 'microbiome', 'gut microbiome', '未病', '予防', '健康寿命',
  ];
  const foodStrong = ['代替肉', '培養肉', '機能性食品', '食品製造', '食品加工'];
  const hasAgri = agriStrong.some(term => text.includes(term.toLowerCase()));
  const hasHealthcare = healthcareStrong.some(term => text.includes(term.toLowerCase()));
  const hasFoodOnly = foodStrong.some(term => text.includes(term.toLowerCase()));
  const negativeSectors = Array.from(new Set([...(p.negative_sectors || []), ...inferNegativeSectorsFromText(raw)]));
  if (negativeSectors.length) p.negative_sectors = negativeSectors;
  if (hasHealthcare) {
    p.tech_domain = 'healthcare';
  }
  if (hasAgri && !hasFoodOnly) {
    p.tech_domain = 'agri';
  }
  const inferredBudget = inferBudgetRangeFromText(raw);
  if (inferredBudget) p.budget_range = inferredBudget;
  if (/アクセラ|アクセラレーター|自治体実証|実証支援/.test(raw)) p.support_type = 'accelerator';
  if (/活動資金|協業費|支援金/.test(raw)) p.support_type = 'activity_fund';
  if (/GAPファンド|ギャップファンド|gap fund/i.test(raw)) p.support_type = 'gap_fund';
  if (/NEDO|STS|SBIR|DTSU|ディープテック/i.test(raw)) p.support_type = 'deeptech_startup';
  if (/自治体PoC|自治体実証|実証フィールド|社会実験/.test(raw)) p.support_type = 'municipality_poc';
  return p;
}

async function proposeFromCompanyUrl(options={}) {
  const input = $('#quickSearchText');
  const inputText = (options.inputText ?? (input && input.value) ?? '').trim();
  const extracted = options.url
    ? {url: options.url, needText: options.needText || ''}
    : extractUrlAndNotes(inputText);
  const url = extracted.url;
  const needText = (options.needText ?? extracted.needText ?? '').trim();
  const autoSearch = options.autoSearch !== false;
  if (!url) {
    appendChatMsg('bot', '会社URLを入れてください。例: https://example.co.jp');
    return;
  }
  beginDirectConversation();
  const btn = $('#companyUrlBtn');
  const originalText = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '読み取り中...'; }
  $('#resultMeta').textContent = '会社URLから条件を下書きしています...';
  appendChatMsg('user', inputText || url);
  appendChatMsg('bot', '会社サイトを読んで、検索条件を下書きします…');
  let data = null;
  try {
    data = await api('/api/company-profile', {method: 'POST', body: JSON.stringify({url, need_text: needText})});
  } catch (err) {
    data = {
      payload: fallbackCompanyPayload(url, needText),
      summary: '会社URLは受け取りました。サイト本文を読み取れなかったため、URLを手がかりに検索します。技術概要を追記すると精度が上がります。',
      confidence: 'URLのみ',
      needs_more_info: true,
    };
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = originalText; }
  }
  try {
    proposedPayload = refineCompanyPayloadFromSummary(data.payload || fallbackCompanyPayload(url, needText), data.summary || '', needText);
    const labels = {
      idea: 'アイデア・シーズ探索', poc: 'PoC・概念実証', prototype: '試作・開発',
      demonstration: '実証・社会実装前', commercialization: '事業化・量産前',
      ai: 'AI・ソフトウェア', medical: '医療・医療機器', bio: 'バイオ・創薬',
      healthcare: 'ヘルスケア', agri: 'アグリテック', foodtech: 'フードテック',
      energy: 'エネルギー・GX', materials: '材料・化学', robotics: 'ロボティクス・製造',
      semiconductor: '半導体・電子', space: '宇宙', other: 'その他',
      development: '研究・試作', validation: 'PoC・実証', equipment: '設備含む',
      startup: 'スタートアップ向け', grant_only: '補助金・助成金',
      accelerator: 'アクセラ・自治体実証', activity_fund: '活動資金・協業費',
      gap_fund: 'GAPファンド', deeptech_startup: 'NEDO・SBIR系',
      municipality_poc: '自治体PoC・実証',
      under5m: '500万円未満', '5m_30m': '500万円〜3000万円',
      '30m_100m': '3000万円〜1億円', over100m: '1億円以上',
    };
    const p = proposedPayload || {};
    const signals = Array.isArray(data.detected_signals) && data.detected_signals.length
      ? `\n読み取った手がかり: ${data.detected_signals.slice(0, 6).join('、')}`
      : '';
    const negativeLabels = {
      medical: '医療・病院系',
      drug_discovery: '創薬・医薬品系',
    };
    const negatives = Array.isArray(p.negative_sectors) && p.negative_sectors.length
      ? ` / 除外: ${p.negative_sectors.map(v => negativeLabels[v] || v).join('、')}`
      : '';
    $('#resultMeta').textContent = '会社URLから条件案を作りました。';
    appendChatMsg(
      'bot',
      `こう見立てました。技術分野: ${labels[p.tech_domain] || p.tech_domain || '要確認'} / 段階: ${labels[p.rd_phase] || p.rd_phase || '要確認'} / 予算: ${labels[p.budget_range] || p.budget_range || '未指定'}${negatives}`,
      autoSearch
        ? [{value: '__edit_profile__', label: '条件を修正する', skip: true}]
        : [
          {value: '__use_profile__', label: 'この条件で検索', skip: true},
          {value: '__edit_profile__', label: '条件を修正する', skip: true},
        ],
      `${data.summary || ''}${signals}`
    );
    if (autoSearch) {
      appendChatMsg('bot', 'この見立てで、候補を先に並べます。理由もカードに出します。');
      useDirectPayload(proposedPayload, null, {preserveChat: true});
    }
  } catch (err) {
    appendChatMsg('bot', err.message || 'URLを受け取れませんでした。自由記述で入力してください。');
  }
}

function resetChat() {
  clearSearchState();
  lastItems = [];
  $('#resultMeta').textContent = '条件を入れると、近い公募を並べます。';
  $('#results').innerHTML = '';
  resetChatState();
  $('#chatMessages').innerHTML = '';
  $('#chatInput').hidden = false;
  showChatStep();
}

async function initChat() {
  try { const data = await api('/api/rd-meta'); chatMeta = data.meta || {}; } catch { chatMeta = {}; }
  resetChatState();
  showChatStep();
}

document.addEventListener('click', e => {
  const detailLink = e.target.closest('[data-detail-link]');
  if (detailLink) {
    detailLink.textContent = 'りこが読みに行ってます...';
    detailLink.setAttribute('aria-busy', 'true');
    detailLink.classList.add('button--loading');
    return;
  }
  const leadBtn = e.target.closest('[data-lead-type]');
  if(leadBtn) openLead(leadBtn.dataset.leadType);
});
$('#chatMessages').addEventListener('click', e => {
  const btn = e.target.closest('.chip-btn');
  if (!btn || btn.disabled) return;
  const val = btn.dataset.value;
  if (val === '__reset__') { resetChat(); return; }
  if (val === '__use_profile__') { useDirectPayload(proposedPayload, 'この条件で検索', {preserveChat: true}); return; }
  if (val === '__edit_profile__') { resetChat(); return; }
  answerChatStep(val, btn.textContent);
});
$('#chatSendBtn').addEventListener('click', () => {
  const input = $('#chatTextInput');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  handleChatFreeInput(text);
});
$('#quickSearchBtn').addEventListener('click', runQuickSearch);
$('#companyUrlBtn').addEventListener('click', proposeFromCompanyUrl);

$('#results').addEventListener('click', onResultClick);
$('#showWatchlist').addEventListener('click', renderWatchlist);
$('#runCompare').addEventListener('click', () => runBulk('/api/compare'));
$('#runReadiness').addEventListener('click', () => runBulk('/api/readiness-check'));
$('#leadForm').addEventListener('submit', submitLead);
$$('[data-dialog-close]').forEach(b => b.addEventListener('click', () => { const d = $('#leadDialog'); if (d.open) d.close(); }));
$('#leadDialog').addEventListener('click', e => { if (e.target === $('#leadDialog') && $('#leadDialog').open) $('#leadDialog').close(); });
$('#leadDialog').addEventListener('close', () => { $('#leadForm').reset(); $('#leadStatus').textContent = ''; });
trackEvent('page_view');
initChat().then(restoreSearchState);
