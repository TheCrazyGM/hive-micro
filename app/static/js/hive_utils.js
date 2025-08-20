// Shared helpers for CSRF token and Hive Keychain signing
(function () {
  function getCsrfToken() {
    try {
      return (
        document.querySelector('meta[name="csrf-token"]')?.content ||
        window.CSRF_TOKEN ||
        ''
      );
    } catch (_) {
      return window.CSRF_TOKEN || '';
    }
  }

  // Returns:
  // - null if signing is required but not possible or user cancelled (shows toasts)
  // - {} if signing not required
  // - { message, signature, pubkey } when signed
  async function requestModerationSignature(action, trxId) {
    try {
      if (!window.HIVE_MOD_REQUIRE_SIG) return {};
      const moderator = localStorage.getItem('hive.username');
      if (!moderator) { if (window.showToast) showToast('Please login first', 'warning'); return null; }
      if (!window.hive_keychain) { if (window.showToast) showToast('Hive Keychain not detected', 'warning'); return null; }
      const msg = `moderation:${action}:${trxId}:${new Date().toISOString()}`;
      const res = await new Promise((resolve) => {
        window.hive_keychain.requestSignBuffer(moderator, msg, 'Posting', function (r) {
          resolve(r);
        });
      });
      if (res && res.success) {
        return {
          message: msg,
          signature: res.result,
          pubkey: res.publicKey || (res.data && res.data.publicKey) || null,
        };
      }
      if (window.showToast) showToast('Signature cancelled', 'info');
      return null;
    } catch (_) {
      if (window.showToast) showToast('Signing failed', 'danger');
      return null;
    }
  }

  window.getCsrfToken = getCsrfToken;
  window.requestModerationSignature = requestModerationSignature;
})();

