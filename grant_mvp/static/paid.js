'use strict';

const $ = (sel, root = document) => root.querySelector(sel);

const PLAN_COPY = {
  basic: {
    title: '簡易診断について相談する',
    desc: 'ご希望のプランやご相談内容をお送りください。担当者よりご連絡します。',
    msg: '【簡易診断】について相談したいです。\n検討中の補助金や状況：',
  },
  standard: {
    title: '標準診断について相談する',
    desc: 'ご希望のプランやご相談内容をお送りください。担当者よりご連絡します。',
    msg: '【標準診断】について相談したいです。\n検討中の補助金や状況：',
  },
  rnd: {
    title: 'R&D詳細診断について相談する',
    desc: 'ご希望のプランやご相談内容をお送りください。担当者よりご連絡します。',
    msg: '【R&D詳細診断】について相談したいです。\n検討中の研究開発テーマ・公募：',
  },
  general: {
    title: '有料診断について相談する',
    desc: 'ご希望のプランやご相談内容をお送りください。担当者よりご連絡します。',
    msg: '有料診断について相談したいです。\n状況やご質問：',
  },
};

function openPaidLead(plan) {
  const copy = PLAN_COPY[plan] || PLAN_COPY.general;
  const dlg = $('#leadDialog');
  const form = $('#leadForm');
  $('#leadTitle').textContent = copy.title;
  $('#leadDescription').textContent = copy.desc;
  $('#leadStatus').textContent = '';
  form.reset();
  form.lead_type.value = 'consultation';
  form.grant_id.value = '';
  form.grant_title.value = `paid_plan:${plan}`;
  form.message.value = `[有料診断申込:${plan}]\n` + copy.msg;
  dlg.showModal();
}

async function submitLead(e) {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target).entries());
  data.source_page = location.pathname;
  try {
    const res = await fetch('/api/lead', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error('送信に失敗しました');
    $('#leadStatus').textContent = '送信しました。担当者よりご連絡します。';
    setTimeout(() => $('#leadDialog').close(), 1400);
  } catch (err) {
    $('#leadStatus').textContent = (err && err.message) || '送信に失敗しました';
  }
}

document.addEventListener('click', (e) => {
  const planBtn = e.target.closest('[data-paid-plan]');
  if (planBtn) {
    e.preventDefault();
    openPaidLead(planBtn.dataset.paidPlan);
    return;
  }
  if (e.target.closest('[data-dialog-close]')) {
    const dlg = $('#leadDialog');
    if (dlg && dlg.open) dlg.close();
  }
});

document.addEventListener('submit', (e) => {
  if (e.target && e.target.id === 'leadForm') submitLead(e);
});
