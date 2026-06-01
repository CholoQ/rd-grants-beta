const $ = (sel, root=document) => root.querySelector(sel);
const tokenKey = 'rikoNaviAdminToken:v1';

function escapeHtml(v) {
  return String(v ?? '').replace(/[&<>"]/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[s]));
}

function metricCard(label, value) {
  return `<article class="analytics-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`;
}

function render(data) {
  const totals = data.totals || {};
  $('#analyticsSummary').innerHTML = [
    metricCard('ページビュー', totals.page_views || 0),
    metricCard('訪問者数', totals.visitors || 0),
    metricCard('検索回数', totals.searches || 0),
  ].join('');
  const rows = data.daily || [];
  $('#analyticsDaily').innerHTML = `
    <h2>日別</h2>
    <table>
      <thead><tr><th>日付</th><th>PV</th><th>訪問者</th><th>検索</th></tr></thead>
      <tbody>
        ${rows.map(row => `
          <tr>
            <td>${escapeHtml(row.day)}</td>
            <td>${escapeHtml(row.page_views || 0)}</td>
            <td>${escapeHtml(row.visitors || 0)}</td>
            <td>${escapeHtml(row.searches || 0)}</td>
          </tr>
        `).join('') || '<tr><td colspan="4">まだ記録がありません</td></tr>'}
      </tbody>
    </table>
  `;
}

async function loadAnalytics() {
  const token = $('#adminToken').value.trim();
  const days = $('#days').value || '30';
  if (!token) {
    $('#analyticsStatus').textContent = 'ADMIN_TOKENを入力してください。';
    return;
  }
  sessionStorage.setItem(tokenKey, token);
  $('#analyticsStatus').textContent = '読み込み中です...';
  try {
    const res = await fetch(`/api/analytics?days=${encodeURIComponent(days)}`, {
      headers: {'X-Admin-Token': token},
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '読み込みに失敗しました');
    render(data);
    $('#analyticsStatus').textContent = `直近${data.days || days}日の集計です。`;
  } catch (err) {
    $('#analyticsStatus').textContent = err.message || '読み込みに失敗しました。';
  }
}

$('#loadAnalytics').addEventListener('click', loadAnalytics);
$('#adminToken').value = sessionStorage.getItem(tokenKey) || '';
if ($('#adminToken').value) loadAnalytics();
