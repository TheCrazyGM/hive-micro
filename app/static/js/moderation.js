document.addEventListener('DOMContentLoaded', () => {
  const trxId = window.__POST_TRX_ID__;
  const reasonEl = document.getElementById('modReason');
  const hideBtn = document.getElementById('modHideBtn');
  const unhideBtn = document.getElementById('modUnhideBtn');
  const logEl = document.getElementById('modLog');

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
    } catch (e) {
      logEl.innerHTML = '<div class="text-danger">Failed to load moderation log</div>';
    }
  }

  async function modAction(action) {
    const payload = { trx_id: trxId };
    if (action === 'hide') payload.reason = (reasonEl && reasonEl.value) || '';
    if (window.HIVE_MOD_REQUIRE_SIG) {
      const moderator = localStorage.getItem('hive.username');
      if (!moderator) { if (window.showToast) showToast('Please login first', 'warning'); return; }
      if (!window.hive_keychain) { if (window.showToast) showToast('Hive Keychain not detected', 'warning'); return; }
      const msg = `moderation:${action}:${trxId}:${new Date().toISOString()}`;
      await new Promise((resolve) => {
        window.hive_keychain.requestSignBuffer(moderator, msg, 'Posting', function (res) {
          if (res && res.success) {
            payload.message = msg;
            payload.signature = res.result;
            payload.pubkey = res.publicKey || (res.data && res.data.publicKey) || null;
            resolve();
          } else {
            if (window.showToast) showToast('Signature cancelled', 'info');
            resolve();
          }
        });
      });
      if (!payload.signature) return;
    }
    try {
      const url = action === 'hide' ? '/api/v1/mod/hide' : '/api/v1/mod/unhide';
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': (document.querySelector('meta[name="csrf-token"]')?.content || window.CSRF_TOKEN || '') },
        body: JSON.stringify(payload)
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.success) throw new Error(d.error || 'Request failed');
      if (window.showToast) showToast(`Post ${action}d successfully`, 'success');
      // Reload page to reflect state
      setTimeout(() => window.location.reload(), 400);
    } catch (e) {
      if (window.showToast) showToast('Moderation failed: ' + e.message, 'danger');
    }
  }

  if (hideBtn) hideBtn.addEventListener('click', () => modAction('hide'));
  if (unhideBtn) unhideBtn.addEventListener('click', () => modAction('unhide'));

  fetchLog();
});
