'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function getQueryId() {
  const params = new URLSearchParams(location.search);
  return (params.get('id') || '').trim();
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

function formatYen(n) {
  if (!n && n !== 0) return '';
  if (n >= 100000000) return `${(n / 100000000).toLocaleString()}億円`;
  if (n >= 10000) return `${(n / 10000).toLocaleString()}万円`;
  return `${n.toLocaleString()}円`;
}

/* ------------------ 質問定義（順序に注意） ------------------ */
const QUESTIONS = [
  {
    key: 'applicant_type',
    label: '申請主体はどれですか？',
    options: [
      { value: 'corp',     label: '法人' },
      { value: 'sole',     label: '個人事業主' },
      { value: 'founding', label: '創業予定' },
      { value: 'other',    label: 'その他' },
    ],
  },
  {
    key: 'location',
    label: '補助金に地域要件がある場合、本社所在地は対象内ですか？',
    options: [
      { value: 'inside',  label: '対象地域内と思われる' },
      { value: 'outside', label: '対象地域外の可能性がある' },
      { value: 'unknown', label: '分からない' },
    ],
  },
  {
    key: 'expense_target',
    label: '主に使いたい経費はどれですか？（単一選択）',
    options: [
      { value: 'equipment', label: '設備投資' },
      { value: 'software',  label: 'システム開発' },
      { value: 'rnd',       label: '研究開発' },
      { value: 'marketing', label: '広告・販路開拓' },
      { value: 'payroll',   label: '人件費' },
      { value: 'undecided', label: 'まだ決まっていない' },
    ],
  },
  {
    key: 'order_status',
    label: '補助対象となる経費について、発注・契約の状況は？',
    options: [
      { value: 'not_yet', label: 'まだ発注していない' },
      { value: 'already', label: 'すでに発注・契約済み' },
      { value: 'unknown', label: '分からない' },
    ],
  },
  {
    key: 'deadline_buffer',
    label: '締切までの余裕はどのくらいですか？',
    options: [
      { value: 'over1m',  label: '1か月以上ある' },
      { value: '2to4w',   label: '2〜4週間' },
      { value: 'under2w', label: '2週間未満' },
      { value: 'unknown', label: '分からない' },
    ],
  },
  {
    key: 'gbiz_id',
    label: 'GビズIDの取得状況は？',
    options: [
      { value: 'have',    label: '取得済み' },
      { value: 'none',    label: '未取得' },
      { value: 'unknown', label: '分からない' },
    ],
  },
  {
    key: 'financials',
    label: '直近の決算書は用意できますか？',
    options: [
      { value: 'ok',      label: '用意できる' },
      { value: 'ng',      label: '用意できない' },
      { value: 'unknown', label: '分からない' },
    ],
  },
  {
    key: 'quotes',
    label: '見積書の取得状況は？',
    options: [
      { value: 'have',     label: '取得済み' },
      { value: 'will_get', label: 'これから取得する' },
      { value: 'none',     label: 'まだない' },
    ],
  },
  {
    key: 'own_funds',
    label: '自己資金の見通しは？',
    options: [
      { value: 'ok',      label: '用意できる' },
      { value: 'worry',   label: '不安がある' },
      { value: 'unknown', label: '分からない' },
    ],
  },
  {
    key: 'tax_arrears',
    label: '税金の未納はありますか？',
    options: [
      { value: 'none',    label: 'ない' },
      { value: 'exists',  label: 'ある' },
      { value: 'unknown', label: '分からない' },
    ],
  },
];

/* ------------------ localStorage ------------------ */
const LS_PREFIX = 'grant_check_answers_v1::';
const LS_INDEX = 'grant_check_index_v1';

function loadSavedAnswers(grantId) {
  try {
    const raw = localStorage.getItem(LS_PREFIX + grantId);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!data || data.version !== 1) return null;
    return data;
  } catch (_) { return null; }
}

function saveAnswers(grantId, grantTitle, answers, resultSnapshot) {
  try {
    const payload = {
      version: 1,
      grant_id: grantId,
      grant_title: grantTitle || '',
      answered_at: new Date().toISOString(),
      answers: answers,
      result_snapshot: resultSnapshot,
    };
    localStorage.setItem(LS_PREFIX + grantId, JSON.stringify(payload));
    let index = [];
    try { index = JSON.parse(localStorage.getItem(LS_INDEX) || '[]'); } catch (_) { index = []; }
    index = index.filter(x => x !== grantId);
    index.push(grantId);
    if (index.length > 20) {
      const removed = index.splice(0, index.length - 20);
      removed.forEach(rid => localStorage.removeItem(LS_PREFIX + rid));
    }
    localStorage.setItem(LS_INDEX, JSON.stringify(index));
  } catch (_) { /* ignore quota errors */ }
}

/* ------------------ 質問の描画 ------------------ */
function renderQuestions() {
  const root = $('#checkQuestions');
  root.innerHTML = QUESTIONS.map((q, idx) => `
    <fieldset class="check-question" data-key="${escapeHtml(q.key)}">
      <legend><span class="check-q-num">Q${idx + 1}</span> ${escapeHtml(q.label)}</legend>
      <div class="check-options">
        ${q.options.map(opt => `
          <label class="check-option">
            <input type="radio" name="${escapeHtml(q.key)}" value="${escapeHtml(opt.value)}" />
            <span>${escapeHtml(opt.label)}</span>
          </label>
        `).join('')}
      </div>
    </fieldset>
  `).join('');
}

function collectAnswers() {
  const out = {};
  for (const q of QUESTIONS) {
    const el = document.querySelector(`input[name="${q.key}"]:checked`);
    out[q.key] = el ? el.value : null;
  }
  return out;
}

function applyAnswers(answers) {
  if (!answers) return;
  for (const q of QUESTIONS) {
    const v = answers[q.key];
    if (!v) continue;
    const el = document.querySelector(`input[name="${q.key}"][value="${CSS.escape(v)}"]`);
    if (el) el.checked = true;
  }
}

function clearAnswers() {
  $$('input[type="radio"]', $('#checkForm')).forEach(el => { el.checked = false; });
}

/* ------------------ 採点ロジック ------------------ */
function bandExclusion(score) {
  if (score >= 3) return 'high';
  if (score >= 1) return 'mid';
  return 'low';
}
function bandPrep(score) {
  if (score >= 4) return 'high';
  if (score >= 2) return 'mid';
  return 'low';
}
function bandLabel(level) {
  return { low: '低', mid: '中', high: '高' }[level] || '—';
}

function evaluate(answers) {
  const exclusionItems = [];
  const reviewItems = [];
  const nextActions = [];
  let exclusionScore = 0;
  let prepScore = 0;
  let unknownCount = 0;

  Object.values(answers).forEach(v => { if (v === 'unknown') unknownCount += 1; });

  if (answers.tax_arrears === 'exists') {
    exclusionScore += 3;
    exclusionItems.push({ level: 'high', label: '税金未納がある場合、応募できない補助金が多くあります。納付状況を確認してください' });
    nextActions.push('未納分の納付・分納相談を検討してください');
  } else if (answers.tax_arrears === 'unknown') {
    exclusionScore += 1;
    reviewItems.push('税金の未納有無を確認してください');
  }

  if (answers.order_status === 'already') {
    exclusionScore += 3;
    exclusionItems.push({ level: 'high', label: '補助対象は交付決定後の発注に限定される制度が多くあります。すでに発注済みの場合は対象外の可能性があります' });
    nextActions.push('契約日・発注日を確認し、公式公募要領で対象範囲を確認してください');
  } else if (answers.order_status === 'unknown') {
    exclusionScore += 1;
    reviewItems.push('発注・契約のタイミングを確認してください');
  }

  if (answers.location === 'outside') {
    exclusionScore += 3;
    exclusionItems.push({ level: 'high', label: '補助金の対象地域に該当しない可能性があります' });
    nextActions.push('公式公募要領で対象地域を確認してください');
  } else if (answers.location === 'unknown') {
    exclusionScore += 1;
    reviewItems.push('補助金の対象地域要件と本社所在地の関係を確認してください');
  }

  if (answers.applicant_type === 'founding') {
    exclusionScore += 1;
    reviewItems.push('創業予定の場合、応募時点で法人格が必要な制度もあります。応募資格を確認してください');
  } else if (answers.applicant_type === 'other') {
    exclusionScore += 1;
    reviewItems.push('申請主体が一般的な区分に当てはまらない場合、対象外となる制度もあります。応募資格を確認してください');
  } else if (answers.applicant_type === 'sole') {
    reviewItems.push('個人事業主は対象外となる補助金もあります。応募資格を確認してください');
  }

  if (answers.deadline_buffer === 'under2w') {
    prepScore += 3;
    reviewItems.push('準備期間が限られています。書類の優先順位付けが必要です');
    nextActions.push('公式公募要領を読み、必要書類のリストアップを最優先で進めてください');
  } else if (answers.deadline_buffer === '2to4w') {
    prepScore += 1;
    reviewItems.push('準備期間が2〜4週間です。早めにスケジュールを組んでください');
  } else if (answers.deadline_buffer === 'unknown') {
    prepScore += 1;
    reviewItems.push('締切日を確認してください');
  }

  if (answers.gbiz_id === 'none') {
    prepScore += 1;
    reviewItems.push('GビズIDの取得が応募条件となっている可能性があります');
    nextActions.push('GビズIDの取得手続きを開始してください');
  } else if (answers.gbiz_id === 'unknown') {
    reviewItems.push('GビズIDの要否を公式公募要領で確認してください');
  }

  if (answers.financials === 'ng') {
    prepScore += 2;
    reviewItems.push('直近決算書の準備状況を確認してください');
    nextActions.push('決算書の入手・整備を進めてください');
  } else if (answers.financials === 'unknown') {
    reviewItems.push('提出が想定される決算書の範囲を確認してください');
  }

  if ((answers.expense_target === 'equipment' || answers.expense_target === 'software') && answers.quotes === 'none') {
    prepScore += 2;
    nextActions.push('複数業者から見積書を取得してください');
  } else if ((answers.expense_target === 'equipment' || answers.expense_target === 'software') && answers.quotes === 'will_get') {
    prepScore += 1;
    nextActions.push('見積書の取得を進めてください');
  } else if (answers.quotes === 'none') {
    reviewItems.push('見積書の要否を公式公募要領で確認してください');
  }

  if (answers.own_funds === 'worry') {
    prepScore += 1;
    reviewItems.push('補助金は後払いが基本で、自己資金や運転資金の準備が必要な場合があります');
  } else if (answers.own_funds === 'unknown') {
    reviewItems.push('自己資金の見通しを確認してください');
  }

  if (answers.expense_target === 'payroll') {
    reviewItems.push('人件費は補助対象範囲が制度ごとに異なります。対象範囲を公式公募要領で確認してください');
  } else if (answers.expense_target === 'undecided') {
    prepScore += 1;
    reviewItems.push('対象経費の方向性を整理してください');
    nextActions.push('補助対象経費の候補を洗い出してください');
  } else if (answers.expense_target === 'marketing') {
    reviewItems.push('研究開発系の制度では広告・販路開拓は対象外となる場合があります。対象経費を公式公募要領で確認してください');
  }

  const exclusion = bandExclusion(exclusionScore);
  const prep = bandPrep(prepScore);

  let verdict;
  if (exclusion === 'high') {
    verdict = 'high_risk';
  } else if (unknownCount >= 3) {
    verdict = 'needs_review';
  } else if ((exclusion === 'low' || exclusion === 'mid') && (prep === 'low' || prep === 'mid')) {
    verdict = 'possible';
  } else {
    verdict = 'needs_review';
  }

  const verdictLabelMap = {
    possible:     '応募を検討できる可能性があります',
    needs_review: '要確認です',
    high_risk:    '対象外リスクが高い可能性があります',
  };
  const verdictCommentMap = {
    possible:     '簡易チェック上は大きな対象外要素は見当たりませんでした。最終的な応募可否は公式公募要領でご確認ください。',
    needs_review: '不明な項目や要確認の項目があります。公式公募要領で要件をご確認ください。',
    high_risk:    '対象外となる可能性がある項目が見つかりました。まずは公式公募要領で要件をご確認ください。',
  };

  if (unknownCount >= 3) {
    reviewItems.push('不明な項目が複数あります。公式公募要領の確認と専門家への相談を検討してください');
  }

  const dedup = (arr) => Array.from(new Set(arr));
  return {
    verdict,
    verdict_label: verdictLabelMap[verdict],
    verdict_comment: verdictCommentMap[verdict],
    exclusion_risk: exclusion,
    prep_risk: prep,
    exclusion_items: exclusionItems,
    review_items: dedup(reviewItems),
    next_actions: dedup(nextActions),
    unknown_count: unknownCount,
  };
}

/* ------------------ 結果の描画 ------------------ */
function renderResult(result) {
  $('#checkOverallComment').textContent = result.verdict_comment;

  const vb = $('#checkVerdictBadge');
  vb.textContent = result.verdict_label;
  vb.className = `check-badge check-badge--verdict-${result.verdict}`;

  const eb = $('#checkExclusionBadge');
  eb.textContent = bandLabel(result.exclusion_risk);
  eb.className = `check-badge check-badge--risk-${result.exclusion_risk}`;

  const pb = $('#checkPrepBadge');
  pb.textContent = bandLabel(result.prep_risk);
  pb.className = `check-badge check-badge--risk-${result.prep_risk}`;

  const ex = $('#checkExclusionList');
  if (!result.exclusion_items.length) {
    ex.innerHTML = '<li class="detail-list__empty">簡易チェック上は対象外要素は見つかりませんでした。最終確認は公式公募要領で行ってください。</li>';
  } else {
    ex.innerHTML = result.exclusion_items.map(r => `
      <li class="detail-risk detail-risk--${escapeHtml(r.level)}">
        <span class="detail-risk__level">${escapeHtml(r.level === 'high' ? '高' : r.level === 'medium' ? '中' : '低')}</span>
        <span class="detail-risk__text">${escapeHtml(r.label)}</span>
      </li>`).join('');
  }

  const rv = $('#checkReviewList');
  if (!result.review_items.length) {
    rv.innerHTML = '<li class="detail-list__empty">特に要確認の項目はありませんでした。最終確認は公式公募要領で行ってください。</li>';
  } else {
    rv.innerHTML = result.review_items.map(x => `<li>${escapeHtml(x)}</li>`).join('');
  }

  const nx = $('#checkNextList');
  if (!result.next_actions.length) {
    nx.innerHTML = '<li class="detail-list__empty">具体的な追加アクションは見つかりませんでした。公式公募要領で全体像をご確認ください。</li>';
  } else {
    nx.innerHTML = result.next_actions.map(x => `<li>${escapeHtml(x)}</li>`).join('');
  }
}

/* ------------------ ページ初期化 ------------------ */
let CURRENT = { grantId: '', grantTitle: '', officialUrl: '' };

function showRestoreIfAny() {
  const saved = loadSavedAnswers(CURRENT.grantId);
  if (!saved) return;
  $('#checkRestoreSection').hidden = false;
}

async function loadHead() {
  const id = getQueryId();
  CURRENT.grantId = id;
  if (!id) {
    $('#checkEyebrow').textContent = 'エラー';
    $('#checkGrantTitle').textContent = 'IDが指定されていません';
    $('#checkGrantFacts').innerHTML = '';
    return;
  }
  $('#checkDetailLink').href = '/detail.html?id=' + encodeURIComponent(id);
  $('#checkBackToDetail').href = '/detail.html?id=' + encodeURIComponent(id);

  try {
    const data = await api('/api/grant-summary?id=' + encodeURIComponent(id));
    CURRENT.grantTitle = data.title || '';
    CURRENT.officialUrl = data.official_url || '';
    $('#checkEyebrow').textContent = (data.summary && data.summary.field) || '研究開発支援';
    $('#checkGrantTitle').textContent = data.title || '名称未設定の公募';

    const s = data.summary || {};
    const facts = [
      ['実施機関',  data.institution_name || data.system_name || data.source || '公式情報で確認してください'],
      ['締切',      s.deadline || '公式公募要領で確認してください'],
      ['補助上限',  data.subsidy_max_limit ? formatYen(data.subsidy_max_limit) : '公式公募要領で確認してください'],
    ];
    $('#checkGrantFacts').innerHTML = facts.map(([k, v]) => `
      <div class="detail-fact">
        <span class="detail-fact__label">${escapeHtml(k)}</span>
        <span class="detail-fact__value">${escapeHtml(v)}</span>
      </div>`).join('');

    if (CURRENT.officialUrl) {
      const b = $('#checkOfficialBtn'); b.href = CURRENT.officialUrl; b.hidden = false;
    }
  } catch (err) {
    $('#checkEyebrow').textContent = 'エラー';
    $('#checkGrantTitle').textContent = '公募情報の取得に失敗しました';
    $('#checkGrantFacts').innerHTML = '';
  }

  showRestoreIfAny();
}

function attachHandlers() {
  $('#checkForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const answers = collectAnswers();
    const missing = Object.values(answers).some(v => !v);
    if (missing) {
      $('#checkValidation').hidden = false;
      $('#checkValidation').scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    $('#checkValidation').hidden = true;
    const result = evaluate(answers);
    saveAnswers(CURRENT.grantId, CURRENT.grantTitle, answers, {
      verdict: result.verdict,
      exclusion_risk: result.exclusion_risk,
      prep_risk: result.prep_risk,
    });
    renderResult(result);
    $('#checkResult').hidden = false;
    $('#checkResult').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  $('#checkResetBtn').addEventListener('click', () => {
    clearAnswers();
    $('#checkValidation').hidden = true;
    $('#checkResult').hidden = true;
  });

  $('#checkRetryBtn').addEventListener('click', () => {
    $('#checkResult').hidden = true;
    $('#checkForm').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  $('#checkRestoreBtn').addEventListener('click', () => {
    const saved = loadSavedAnswers(CURRENT.grantId);
    if (!saved || !saved.answers) return;
    applyAnswers(saved.answers);
    $('#checkRestoreSection').hidden = true;
  });

  $('#checkDismissRestoreBtn').addEventListener('click', () => {
    $('#checkRestoreSection').hidden = true;
  });
}

renderQuestions();
attachHandlers();
loadHead();
