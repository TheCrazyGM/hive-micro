document.addEventListener('DOMContentLoaded', () => {
  const tbody = document.getElementById('modTableBody');
  const loadMoreBtn = document.getElementById('loadMoreBtn');
  const statusFilter = document.getElementById('statusFilter');
  const refreshBtn = document.getElementById('refreshBtn');
  let cursor = null;
  let loading = false;

  function esc(s) { return String(s).replace(/[&<>"]+/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

  async function load(reset=false) {
    if (loading) return; loading = true; loadMoreBtn.disabled = true;
    if (reset) { tbody.innerHTML=''; cursor = null; }
    try {
      const p = new URLSearchParams();
      p.set('limit','20');
      if (cursor) p.set('cursor', cursor);
      const status = (statusFilter?.value || 'all');
      if (status && status !== 'all') p.set('status', status);
      const r = await fetch(`/api/v1/mod/list?${p.toString()}`);
      const d = await r.json();
      const items = Array.isArray(d.items) ? d.items : [];
      if (items.length === 0 && !tbody.children.length) {
        tbody.innerHTML = '<tr><td class="text-muted" colspan="6">No items.</td></tr>';
      }
      for (const it of items) {
        const tr = document.createElement('tr');
        const dt = new Date(it.timestamp).toLocaleString();
        const tags = Array.isArray(it.tags) ? it.tags.map(t=>`#${esc(t)}`).join(' ') : '';
        const pendingInfo = it.pending ? `<span class="badge text-bg-info">Pending ${Number(it.approvals)||0}/${Number(it.quorum)||0}</span>` : '';
        const statusHtml = it.hidden ? `<span class="badge text-bg-warning">Hidden</span>` : '<span class="badge text-bg-success">Public</span>';
        tr.innerHTML = `
          <td class="small text-muted">${dt}</td>
          <td><a href="/u/${encodeURIComponent(String(it.author).toLowerCase())}">@${esc(it.author)}</a></td>
          <td style="max-width: 40ch; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${esc(it.content || '')}</td>
          <td class="small text-muted">${tags}</td>
          <td><div class="d-flex gap-1 align-items-center">${statusHtml}${pendingInfo ? ' ' + pendingInfo : ''}</div></td>
          <td class="text-end">
            <div class="btn-group btn-group-sm">
              <a class="btn btn-outline-secondary" href="/p/${encodeURIComponent(it.trx_id)}">Open</a>
              ${it.hidden ? `<button class="btn btn-success" data-act="unhide" data-trx="${esc(it.trx_id)}">Unhide</button>` : `<button class="btn btn-danger" data-act="hide" data-trx="${esc(it.trx_id)}">Hide</button>`}
              <button class="btn btn-outline-secondary" data-act="log" data-trx="${esc(it.trx_id)}">Log</button>
            </div>
          </td>`;
        tbody.appendChild(tr);
      }
      if (items.length) {
        cursor = items[items.length - 1].timestamp;
        loadMoreBtn.disabled = false;
      }
    } catch (e) {
      if (!tbody.children.length) tbody.innerHTML = '<tr><td class="text-danger" colspan="6">Failed to load</td></tr>';
    } finally { loading = false; }
  }

  tbody.addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const act = btn.getAttribute('data-act');
    const trx = btn.getAttribute('data-trx');
    if (!trx) return;
    if (act === 'log') {
      try {
        const r = await fetch(`/api/v1/mod/log/${encodeURIComponent(trx)}`);
        const d = await r.json();
        const items = Array.isArray(d.items) ? d.items : [];
        const lines = items.map(a=>`[${new Date(a.created_at).toLocaleString()}] ${a.action} by @${a.moderator}${a.reason? ' — ' + a.reason : ''}`).join('\n');
        if (window.showInfoModal) {
          await showInfoModal({ title: 'Moderation Log', text: lines || 'No actions' });
        } else {
          alert(lines || 'No actions');
        }
      } catch (err) {
        if (window.showToast) showToast('Failed to load log', 'danger');
      }
      return;
    }
    if (act === 'hide') {
      const payload = { trx_id: trx };
      if (window.HIVE_MOD_REASON_REQUIRED && window.showReasonModal) {
        const rsn = await showReasonModal({ title: 'Reason to hide', required: true });
        if (rsn == null) return; payload.reason = rsn;
      }
      if (window.requestModerationSignature) {
        const sig = await window.requestModerationSignature('hide', trx);
        if (sig === null) return; Object.assign(payload, sig);
      }
      try {
        const csrf = (window.getCsrfToken ? window.getCsrfToken() : (document.querySelector('meta[name="csrf-token"]')?.content || window.CSRF_TOKEN || ''));
        const r = await fetch('/api/v1/mod/hide', { method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token': csrf}, body: JSON.stringify(payload)});
        const d = await r.json().catch(() => ({}));
        if (!r.ok || !d.success) throw new Error(d.error||'failed');
        if (d.hidden) {
          if (window.showToast) showToast('Post hidden', 'success');
        } else if (typeof d.approvals === 'number' && typeof d.quorum === 'number') {
          if (window.showToast) showToast(`Pending: ${d.approvals}/${d.quorum} approvals`, 'info');
        } else {
          if (window.showToast) showToast('Hide recorded', 'info');
        }
        load(true);
      } catch (err) { if (window.showToast) showToast('Hide failed', 'danger'); }
      return;
    }
    if (act === 'unhide') {
      const payload = { trx_id: trx };
      if (window.requestModerationSignature) {
        const sig = await window.requestModerationSignature('unhide', trx);
        if (sig === null) return; Object.assign(payload, sig);
      }
      try {
        const csrf = (window.getCsrfToken ? window.getCsrfToken() : (document.querySelector('meta[name="csrf-token"]')?.content || window.CSRF_TOKEN || ''));
        const r = await fetch('/api/v1/mod/unhide', { method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token': csrf}, body: JSON.stringify(payload)});
        const d = await r.json(); if (!r.ok || !d.success) throw new Error(d.error||'failed');
        if (window.showToast) showToast('Post unhidden', 'success');
        load(true);
      } catch (err) { if (window.showToast) showToast('Unhide failed', 'danger'); }
      return;
    }
  });

  load(true);
  loadMoreBtn.addEventListener('click', ()=> load(false));
  refreshBtn.addEventListener('click', ()=> load(true));
  statusFilter.addEventListener('change', ()=> load(true));
});
