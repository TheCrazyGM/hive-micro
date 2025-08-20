// Simple Bootstrap 5 toast helper
// Usage: showToast('Message', 'success'|'danger'|'warning'|'info')
(function () {
  function showToast(message, variant) {
    try {
      var container = document.getElementById('toast-container');
      if (!container) return alert(message);
      var v = String(variant || 'info').toLowerCase();
      var cls = 'text-bg-' + (v === 'error' ? 'danger' : v);
      var el = document.createElement('div');
      el.className = 'toast align-items-center ' + cls + ' border-0';
      el.setAttribute('role', 'alert');
      el.setAttribute('aria-live', 'assertive');
      el.setAttribute('aria-atomic', 'true');
      el.innerHTML = '<div class="d-flex">'
      + '<div class="toast-body">' + String(message) + '</div>'
      + '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>'
      + '</div>';
      container.appendChild(el);
      var t = new bootstrap.Toast(el, { delay: 4000, autohide: true });
      el.addEventListener('hidden.bs.toast', function () {
        el.remove();
      });
      t.show();
    } catch (e) {
      try { alert(message); } catch (_) {}
    }
  }
  window.showToast = showToast;
})();

