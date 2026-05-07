const $ = (sel, root=document) => root.querySelector(sel);
const $$ = (sel, root=document) => Array.from(root.querySelectorAll(sel));
const watchKey = 'rdFundingWatchlist:v1';
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

async function api(path, options={}){
  const res = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
  const data = await res.json().catch(()=>({}));
  if(!res.ok) throw new Error(data.error || 'API error');
  return data;
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

function renderSummaryHtml(data) {
  const s = data.summary || data;
  const srcLabel = getSummarySourceLabel(data.summary_source || s.summary_source);

  function sec(icon, label, content) {
    if (!content) return '';
    return `<div class="sum-section"><div class="sum-section-head">${icon} ${escapeHtml(label)}</div>${content}</div>`;
  }

  function textVal(val) {
    const text = String(val || '');
    return (!text || text === '要確認' || text === 'unknown') ? '' : text;
  }

  function listItems(arr) {
    const items = (arr && arr.length) ? arr : ['要確認'];
    if (items.length === 1 && items[0] === '要確認') return '';
    return `<ul class="sum-list">${items.map(v => `<li>${escapeHtml(String(v))}</li>`).join('')}</ul>`;
  }

  function tag(icon, val) {
    const text = textVal(val);
    return text ? `<span class="sum-tag">${icon} ${escapeHtml(text)}</span>` : '';
  }

  const budgetTags = parseBudget(s.budget).map(t => `<span class="sum-tag">💰 ${escapeHtml(t)}</span>`).join('');
  const dlText = formatDeadline(s.deadline);
  const phaseLabel = RD_PHASE_LABELS[s.rd_phase] || '';
  const tags = [
    budgetTags,
    dlText     ? `<span class="sum-tag">📅 ${escapeHtml(dlText)}</span>`          : '',
    phaseLabel ? `<span class="sum-tag">🔬 フェーズ：${escapeHtml(phaseLabel)}</span>` : '',
  ].filter(Boolean).join('');

  const rows = [
    `<div class="sum-source">生成元: ${escapeHtml(srcLabel)}</div>`,
    textVal(s.overview) ? `<div class="sum-overview">${escapeHtml(textVal(s.overview))}</div>` : '',
    textVal(s.purpose)  ? `<div class="sum-purpose">${escapeHtml(textVal(s.purpose))}</div>`   : '',
    tags ? `<div class="sum-tags">${tags}</div>` : '',
    sec('✅', 'こんな会社に合いそう',        listItems(getArr(s, 'suitable_for'))),
    sec('⚠️', '合わないかもしれない会社',    listItems(getArr(s, 'not_suitable_for'))),
    sec('👥', '誰が応募できる？',            listItems(getArr(s, 'target_companies', 'target_conditions'))),
    sec('💡', '何に使えるお金？',            listItems(getArr(s, 'eligible_expenses'))),
    sec('📋', '用意するもの',                listItems(getArr(s, 'required_documents'))),
    sec('✏️', 'まずやること',               listItems(getArr(s, 'preparation_tasks', 'application_steps'))),
    sec('🙋', '相談するならこの人',          listItems(getArr(s, 'expert_type_needed'))),
    sec('❓', '確認しておきたいこと',        listItems(getArr(s, 'first_questions_to_ask'))),
    sec('⚡', '気をつけること',              listItems(getArr(s, 'cautions'))),
  ];
  const body = rows.filter(Boolean).join('');
  const fallback = body ? '' : '<p class="sum-soft-unknown">詳細は公式要領でご確認ください。</p>';
  return body + fallback;
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
  if (region) return `${region[1]}の事業者が対象です`;
  return r;
}

function renderItems(items) {
  const root = $('#results');
  if (!items.length) {
    root.innerHTML = '<div class="result-card">候補が見つかりませんでした。条件を広げるか、地域・金額帯を未指定にしてください。</div>';
    return;
  }
  const INITIAL_LIMIT = 5;
  function renderCards(list) {
    return list.map(item => `
      <article class="result-card" data-id="${escapeHtml(item.id)}">
        <h3>${escapeHtml(item.title)}</h3>
        <div class="meta">
          <span class="pill">${escapeHtml(item.institution_name || item.system_name || item.source || '制度')}</span>
          <span class="pill pill--score">一致度 ${escapeHtml(item.match_score ?? item.fit_percent ?? '-')}%</span>
          <span class="pill">${escapeHtml(item.status || '要確認')}</span>
          <span class="pill">${escapeHtml(item.budget_scale_label || '')}</span>
        </div>
        <p>${escapeHtml(item.match_summary || item.detail_plain || item.subsidy_catch_phrase || '詳細は公式ページを確認してください。')}</p>
        ${(item.match_reasons||[]).length ? `<div class="match-reasons"><p class="match-reasons-head">なぜおすすめ？</p><ul>${(item.match_reasons||[]).flatMap(r=>r.split(' / ')).slice(0,5).map(r=>`<li>${escapeHtml(humanizeReason(r))}</li>`).join('')}</ul></div>` : ''}
        ${(item.match_cautions||[]).length ? `<p><strong>要確認:</strong> ${escapeHtml((item.match_cautions||[]).join(' / '))}</p>` : ''}
        <div class="result-actions">
          <button class="button button--small" data-action="summary">やさしく読む</button>
          <button class="button button--small" data-action="watch">ウォッチに保存</button>
          <button class="button button--small" data-action="consult">専門家に相談</button>
          ${item.safe_public_url ? `<a class="button button--small" href="${escapeHtml(item.safe_public_url)}" target="_blank" rel="noopener">公式ページ</a>` : ''}
        </div>
        <div class="details" hidden></div>
      </article>
    `).join('');
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
    const data = await api('/api/rd-search', {method:'POST', body:JSON.stringify(formPayload(e.target))});
    lastItems = data.items || [];
    const counts = data.source_counts || {};
    $('#resultMeta').textContent = `${lastItems.length}件の候補を表示中。Jグランツ ${counts.jgrants_items||0} / NEDO ${counts.nedo_items||0} / JST ${counts.jst_items||0} / AMED ${counts.amed_items||0}`;
    renderItems(lastItems);
  }catch(err){ $('#resultMeta').textContent = '検索に失敗しました: '+err.message; }
}

async function onResultClick(e){
  const btn = e.target.closest('button[data-action]'); if(!btn) return;
  const card = e.target.closest('.result-card');
  const id = card.dataset.id;
  const item = lastItems.find(x => String(x.id)===String(id)) || getWatchlist().find(x => String(x.id)===String(id));
  if(btn.dataset.action === 'watch'){
    addWatch(item); btn.textContent = '保存しました'; return;
  }
  if(btn.dataset.action === 'consult'){
    openLead('consultation', item); return;
  }
  if(btn.dataset.action === 'summary'){
    const box = $('.details', card); box.hidden = false; box.textContent = '要点を取得中です...';
    try{
      const data = await api('/api/grant-summary?id='+encodeURIComponent(id));
      box.innerHTML = renderSummaryHtml(data);
    }catch(err){ box.textContent = '要約取得に失敗しました: '+err.message; }
  }
}

function renderWatchlist(){
  const items = getWatchlist();
  $('#resultMeta').textContent = `ウォッチリスト ${items.length}件`;
  $('#results').innerHTML = items.length ? items.map(item => `
    <article class="result-card" data-id="${escapeHtml(item.id)}">
      <h3>${escapeHtml(item.title)}</h3>
      <div class="meta"><span class="pill">${escapeHtml(item.institution_name||'保存済み')}</span><span class="pill pill--score">${escapeHtml(item.match_score ?? '-')}%</span></div>
      <div class="result-actions">
        <button class="button button--small" data-action="summary">やさしく読む</button>
        <button class="button button--small" onclick="removeWatch('${escapeHtml(item.id)}'); renderWatchlist();">削除</button>
        <button class="button button--small" data-action="consult">専門家に相談</button>
      </div>
      <div class="details" hidden></div>
    </article>`).join('') : '<div class="result-card">まだ保存された公募はありません。</div>';
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
    {value:'bio',          label:'バイオ・医療'},
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
  {key:'rd_phase',    metaKey:'rd_phases',       question:'研究開発のフェーズはどのあたりですか？',  placeholder:'例：PoC段階、試作を終えたところ'},
  {key:'tech_domain', metaKey:'tech_domains',    question:'技術・分野を教えてください。',           placeholder:'例：AIを使った医療診断ツール'},
  {key:'support_type',metaKey:'support_types',   question:'どのような支援を探していますか？',       placeholder:'例：試作費用を補助してほしい'},
  {key:'budget_range',metaKey:'budget_ranges',   question:'希望する資金規模はどのくらいですか？',   placeholder:'例：1000万円程度、大きいほど良い'},
  {key:'region_text', staticOptions:REGION_OPTIONS, question:'事業拠点の地域を教えてください。',    placeholder:'例：神奈川県横浜市、北海道'},
  {key:'free_text', isFinal:true, skipLabel:'このまま検索する',
   question:'最後に、自社の状況や探している資金について補足があれば教えてください。（任意）',
   placeholder:'例：大学発スタートアップで試作費と人件費に使える補助金を探しています。'},
];

const MAIN_STEP_COUNT = STEPS.filter(s => !s.isFinal).length; // 5

let chatMeta = {};
let chatParams = {};
let chatStep = 0;
let chatFreeNotes = [];

function resetChatState() {
  chatParams = {
    rd_phase: '', tech_domain: '', support_type: 'any',
    budget_range: '', region_text: '', free_text: '',
    sources: ['jgrants', 'nedo', 'jst', 'amed'],
    fast_mode: true,
  };
  chatStep = 0;
  chatFreeNotes = [];
}

function getChipOptions(step) {
  if (step.staticOptions) return step.staticOptions;
  const fromMeta = step.metaKey && chatMeta[step.metaKey];
  if (fromMeta) return fromMeta.filter(o => o.value !== '');
  return FALLBACK_OPTIONS[step.key] || [];
}

function appendChatMsg(role, text, chips) {
  const container = $('#chatMessages');
  const msg = document.createElement('div');
  msg.className = `chat-msg chat-msg--${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  bubble.textContent = text;
  msg.appendChild(bubble);
  if (chips && chips.length) {
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
  appendChatMsg('bot', step.question, chips);
  const input = $('#chatTextInput');
  input.placeholder = step.placeholder || '自由に入力...';
  $('#chatInput').hidden = false;
  setTimeout(() => input.focus(), 50);
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
  appendChatMsg('bot', '条件が揃いました。検索しています…');
  $('#resultMeta').textContent = '検索中です...';
  $('#results').innerHTML = '';
  setTimeout(() => document.querySelector('.layout')?.scrollIntoView({behavior: 'smooth', block: 'start'}), 500);
  try {
    const data = await api('/api/rd-search', {method: 'POST', body: JSON.stringify(chatParams)});
    lastItems = data.items || [];
    const c = data.source_counts || {};
    $('#resultMeta').textContent = `${lastItems.length}件の候補を表示中。Jグランツ ${c.jgrants_items||0} / NEDO ${c.nedo_items||0} / JST ${c.jst_items||0} / AMED ${c.amed_items||0}`;
    renderItems(lastItems);
    appendChatMsg('bot', `${lastItems.length}件の候補が見つかりました。下にスクロールしてご確認ください。`,
      [{value: '__reset__', label: '条件を変えて再検索', skip: true}]);
  } catch (err) {
    $('#resultMeta').textContent = '検索に失敗しました: ' + err.message;
    appendChatMsg('bot', 'エラーが発生しました。もう一度お試しください。',
      [{value: '__reset__', label: 'やり直す', skip: true}]);
  }
}

function resetChat() {
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
  const leadBtn = e.target.closest('[data-lead-type]');
  if(leadBtn) openLead(leadBtn.dataset.leadType);
});
$('#chatMessages').addEventListener('click', e => {
  const btn = e.target.closest('.chip-btn');
  if (!btn || btn.disabled) return;
  const val = btn.dataset.value;
  if (val === '__reset__') { resetChat(); return; }
  answerChatStep(val, btn.textContent);
});
$('#chatSendBtn').addEventListener('click', () => {
  const input = $('#chatTextInput');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  handleChatFreeInput(text);
});

$('#results').addEventListener('click', onResultClick);
$('#showWatchlist').addEventListener('click', renderWatchlist);
$('#runCompare').addEventListener('click', () => runBulk('/api/compare'));
$('#runReadiness').addEventListener('click', () => runBulk('/api/readiness-check'));
$('#leadForm').addEventListener('submit', submitLead);
$$('[data-dialog-close]').forEach(b => b.addEventListener('click', () => { const d = $('#leadDialog'); if (d.open) d.close(); }));
$('#leadDialog').addEventListener('click', e => { if (e.target === $('#leadDialog') && $('#leadDialog').open) $('#leadDialog').close(); });
$('#leadDialog').addEventListener('close', () => { $('#leadForm').reset(); $('#leadStatus').textContent = ''; });
initChat();
