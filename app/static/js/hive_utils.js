// Shared helpers for CSRF token and Hive Keychain signing
(function () {
  // HTML escape
  function escapeHTML(s) {
    try {
      return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\"/g, '&quot;')
        .replace(/'/g, '&#39;');
    } catch (_) {
      return '' + s;
    }
  }
  window.escapeHTML = escapeHTML;

  // Linkify @mentions to /u/<username> and #tags to /feed?tag=<tag>
  function linkifyText(text) {
    var esc = escapeHTML(text || '');
    var withMentions = esc.replace(/(^|\s)@([a-z0-9\-\.]+)/gi, function (m, pre, u) {
      var uname = encodeURIComponent(String(u).toLowerCase());
      return pre + '<a href="/u/' + uname + '">@' + u + '</a>';
    });
    var withTags = withMentions.replace(/(^|\s)#([a-z0-9\-]+)/gi, function (m, pre, t) {
      var tag = encodeURIComponent(String(t).toLowerCase());
      return pre + '<a href="/feed?tag=' + tag + '">#' + t + '</a>';
    });
    return withTags;
  }
  window.linkifyText = linkifyText;

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

  function setMentionBadge(count) {
    try {
      var badge = document.getElementById('nav-mentions-count');
      if (!badge) return;
      var n = Number(count) || 0;
      badge.textContent = n;
      badge.className = n > 0 ? 'badge text-bg-primary' : 'badge text-bg-secondary';
    } catch (_) {}
  }
  window.setMentionBadge = setMentionBadge;

  function setFeedNewBadge(count) {
    try {
      var badge = document.getElementById('nav-feed-new-count');
      if (!badge) return;
      var n = Number(count) || 0;
      if (n > 0) {
        badge.textContent = n;
        badge.classList.remove('d-none');
        badge.className = 'badge text-bg-primary';
      } else {
        badge.textContent = '0';
        badge.classList.add('d-none');
        badge.className = 'badge text-bg-secondary d-none';
      }
    } catch (_) {}
  }
  window.setFeedNewBadge = setFeedNewBadge;

  function setNewPostsBanner(count) {
    try {
      var banner = document.getElementById('newPostsBanner');
      var num = document.getElementById('newPostsCount');
      if (!banner || !num) return;
      var n = Number(count) || 0;
      if (n > 0) {
        num.textContent = n;
        banner.classList.remove('d-none');
      } else {
        banner.classList.add('d-none');
      }
    } catch (_) {}
  }
  window.setNewPostsBanner = setNewPostsBanner;

  // Build a consistent avatar <img> for a Hive username
  function createAvatarImg(username, size) {
    try {
      var uname = String(username || '').toLowerCase();
      var img = document.createElement('img');
      img.src = 'https://images.hive.blog/u/' + encodeURIComponent(uname) + '/avatar';
      img.alt = '@' + (window.escapeHTML ? escapeHTML(username) : username);
      img.width = size || 32;
      img.height = size || 32;
      img.loading = 'lazy';
      img.className = 'rounded-circle flex-shrink-0';
      img.style.objectFit = 'cover';
      return img;
    } catch (_) {
      return document.createElement('img');
    }
  }
  window.createAvatarImg = createAvatarImg;

  // Build tag chips container for a tags array
  // opts: { basePath: '?tag=', itemClass: 'badge tag-chip text-decoration-none', extraItemClass: '' }
  function buildTagChips(tags, opts) {
    var options = opts || {};
    var basePath = options.basePath || '/feed?tag=';
    var itemClass = options.itemClass || 'badge tag-chip text-decoration-none';
    var extra = options.extraItemClass || '';
    var wrap = document.createElement('div');
    wrap.className = 'd-flex flex-wrap gap-1 mb-2';
    try {
      if (Array.isArray(tags)) {
        tags.forEach(function (t) {
          var a = document.createElement('a');
          a.href = basePath + encodeURIComponent(String(t).toLowerCase());
          a.className = itemClass + (extra ? (' ' + extra) : '');
          a.textContent = '#' + t;
          wrap.appendChild(a);
        });
      }
    } catch (_) {}
    return wrap;
  }
  window.buildTagChips = buildTagChips;

  // Build an "in reply to" indicator element if reply_to provided
  function buildReplyIndicator(reply_to) {
    if (!reply_to) return null;
    var el = document.createElement('div');
    el.className = 'reply-indicator small mb-1';
    var parentLink = '/p/' + encodeURIComponent(String(reply_to));
    el.innerHTML = 'in reply to <a href="' + parentLink + '">parent</a>';
    return el;
  }
  window.buildReplyIndicator = buildReplyIndicator;

  // Build a transaction link with a short hash
  function buildTrxLink(trxId) {
    try {
      var full = String(trxId || '');
      var pid = encodeURIComponent(full);
      var short = (window.escapeHTML ? escapeHTML(full.slice(0,8)) : full.slice(0,8)) + '…' + (window.escapeHTML ? escapeHTML(full.slice(-8)) : full.slice(-8));
      var title = window.escapeHTML ? escapeHTML(full) : full;
      return '<a class="text-decoration-none" href="/p/' + pid + '" title="' + title + '"><code class="trx-hash">' + short + '</code></a>';
    } catch (_) {
      return '';
    }
  }
  window.buildTrxLink = buildTrxLink;
})();
