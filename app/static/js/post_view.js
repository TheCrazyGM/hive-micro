document.addEventListener('DOMContentLoaded', () => {
  function getCsrf() {
    try {
      if (window.getCsrfToken) return window.getCsrfToken();
      const m = document.querySelector('meta[name="csrf-token"]');
      if (m && m.content) return m.content;
      if (window.CSRF_TOKEN) return window.CSRF_TOKEN;
    } catch (e) {}
    return '';
  }

  function attachHeart(el) {
    if (!el) return;
    const trxId = el.getAttribute('data-trx-id');
    if (!trxId) return;
    const countSpan = el.querySelector('.heart-count');
    const getCount = () => Number((countSpan && countSpan.textContent) || '0') || 0;
    const setState = (count, on) => {
      el.className = on ? 'heart-btn btn btn-sm btn-danger' : 'heart-btn btn btn-sm btn-outline-danger';
      if (countSpan) countSpan.textContent = String(count);
      el.setAttribute('data-hearted', on ? '1' : '0');
    };
    // Initialize state from attributes
    setState(getCount(), el.getAttribute('data-hearted') === '1');

    el.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      try {
        const on = el.getAttribute('data-hearted') === '1';
        const url = on ? '/api/v1/unheart' : '/api/v1/heart';
        const r = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrf() },
          body: JSON.stringify({ trx_id: trxId })
        });
        const d = await r.json().catch(() => ({ success: false }));
        if (!r.ok || d.success !== true) throw new Error(d.error || 'Request failed');
        const nextOn = !!d.viewer_hearted;
        const nextCount = typeof d.hearts === 'number' ? d.hearts : getCount();
        setState(nextCount, nextOn);
      } catch (err) {
        if (window.showToast) showToast('Failed to update heart: ' + err.message, 'danger');
      }
    });
  }

  document.querySelectorAll('.heart-btn').forEach(attachHeart);
});
