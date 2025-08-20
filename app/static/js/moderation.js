document.addEventListener('DOMContentLoaded', () => {
  const trxId = window.__POST_TRX_ID__;
  const reasonEl = document.getElementById('modReason');
  const hideBtn = document.getElementById('modHideBtn');
  const unhideBtn = document.getElementById('modUnhideBtn');
  const logEl = document.getElementById('modLog');
  const statusEl = document.getElementById('modStatus');

  async function fetchLog() {
    if (!logEl) return;
    logEl.innerHTML = '<div class="text-muted">Loading moderation log…</div>';
    try {
      const r = await fetch(`/api/v1/mod/log/${encodeURIComponent(trxId)}`);
      const d = await r.json();
      const items = Array.isArray(d.items) ? d.items : [];
      if (!items.length) {
        logEl.innerHTML = '<div class="text-muted">No moderation actions yet.</div>';
        return;
      }
      const list = document.createElement('ul');
      list.className = 'list-group';
      for (const a of items) {
        const li = document.createElement('li');
        li.className = 'list-group-item d-flex justify-content-between align-items-start';
        const left = document.createElement('div');
        left.innerHTML = `<strong>${a.action}</strong> by @${a.moderator}${a.reason ? ` — ${a.reason}` : ''}`;
        const right = document.createElement('small');
        right.className = 'text-muted';
        right.textContent = new Date(a.created_at).toLocaleString();
        li.appendChild(left);
        li.appendChild(right);
        list.appendChild(li);
      }
      logEl.innerHTML = '';
      logEl.appendChild(list);
      // Update inline pending status if applicable
      try {
        const quorum = Number(window.__MOD_QUORUM__ || 1);
        const hidden = !!window.__POST_HIDDEN__;
        let lastUnhide = null;
        for (const a of items) {
          if (a.action === 'unhide') {
            const t = new Date(a.created_at).getTime();
            if (lastUnhide === null || t > lastUnhide) lastUnhide = t;
          }
        }
        const approvers = new Set();
        for (const a of items) {
          if (a.action !== 'hide') continue;
          const t = new Date(a.created_at).getTime();
          if (lastUnhide !== null && t <= lastUnhide) continue;
          approvers.add(a.moderator);
        }
        const approvals = approvers.size;
        if (!hidden && approvals > 0 && approvals < quorum && statusEl) {
          statusEl.textContent = `Pending: ${approvals}/${quorum} approvals`;
        } else if (statusEl) {
          statusEl.textContent = '';
        }
      } catch (e) { /* ignore */ }
    } catch (e) {
      logEl.innerHTML = '<div class="text-danger">Failed to load moderation log</div>';
    }
  }

  async function modAction(action) {
    const payload = { trx_id: trxId };
    if (action === 'hide') payload.reason = (reasonEl && reasonEl.value) || '';
    if (window.requestModerationSignature) {
      const sig = await window.requestModerationSignature(action, trxId);
      if (sig === null) return; Object.assign(payload, sig);
    }
    try {
      const url = action === 'hide' ? '/api/v1/mod/hide' : '/api/v1/mod/unhide';
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': (window.getCsrfToken ? window.getCsrfToken() : (document.querySelector('meta[name="csrf-token"]')?.content || window.CSRF_TOKEN || '')) },
        body: JSON.stringify(payload)
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.success) throw new Error(d.error || 'Request failed');
      if (action === 'hide' && !d.hidden) {
        if (typeof d.approvals === 'number' && typeof d.quorum === 'number') {
          if (window.showToast) showToast(`Pending: ${d.approvals}/${d.quorum} approvals`, 'info');
          if (statusEl) statusEl.textContent = `Pending: ${d.approvals}/${d.quorum} approvals`;
        } else if (window.showToast) {
          showToast('Hide recorded', 'info');
        }
        // Refresh log without reloading page
        fetchLog();
      } else {
        if (window.showToast) showToast(`Post ${action}d successfully`, 'success');
        setTimeout(() => window.location.reload(), 400);
      }
    } catch (e) {
      if (window.showToast) showToast('Moderation failed: ' + e.message, 'danger');
    }
  }

  if (hideBtn) hideBtn.addEventListener('click', () => modAction('hide'));
  if (unhideBtn) unhideBtn.addEventListener('click', () => modAction('unhide'));

  fetchLog();
});
