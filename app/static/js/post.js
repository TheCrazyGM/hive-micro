document.addEventListener("DOMContentLoaded", function () {
  const postForm = document.getElementById("postForm");
  const appId = (typeof window !== 'undefined' && window.HIVE_APP_ID) ? window.HIVE_APP_ID : 'hive.micro';
  const MAX_LEN = (typeof window !== 'undefined' && window.HIVE_MAX_CONTENT_LEN) ? Number(window.HIVE_MAX_CONTENT_LEN) : 512;
  const ta = document.getElementById("postContent");
  const counterEl = document.getElementById('charCounter');
  const params = new URLSearchParams(window.location.search);
  const replyTo = params.get('reply_to');
  const replyAuthor = params.get('author');
  const notice = document.getElementById('replyNotice');
  const preview = document.getElementById('replyPreview');

  function escapeHTML(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
  function linkify(text) {
    const esc = escapeHTML(text || '');
    const withMentions = esc.replace(/(^|\s)@([a-z0-9\-\.]+)/gi, (m, pre, u) => {
      const uname = encodeURIComponent(u.toLowerCase());
      return `${pre}<a href="/u/${uname}">@${u}</a>`;
    });
    const withTags = withMentions.replace(/(^|\s)#([a-z0-9\-]+)/gi, (m, pre, t) => {
      const tag = encodeURIComponent(t.toLowerCase());
      return `${pre}<a href="/feed?tag=${tag}">#${t}</a>`;
    });
    return withTags;
  }
  // Override with shared helpers if available
  try {
    if (window.escapeHTML) {
      escapeHTML = function (s) { return window.escapeHTML(s); };
    }
    if (window.linkifyText) {
      linkify = function (t) { return window.linkifyText(t); };
    }
  } catch (e) {}
  if (replyTo && notice) {
    const who = replyAuthor ? ` @${replyAuthor}` : '';
    notice.classList.remove('d-none');
    notice.innerHTML = `Replying to<strong>${who}</strong>`;
  }
  // Load compact parent preview
  if (replyTo && preview) {
    (async () => {
      try {
        const res = await fetch(`/api/v1/post/${encodeURIComponent(replyTo)}`);
        if (!res.ok) throw new Error("load failed");
        const data = await res.json();
        const item = data && data.item ? data.item : null;
        if (!item) return;
        const author = escapeHTML(item.author);
        const authorSlug = encodeURIComponent(String(item.author).toLowerCase());
        const dtStr = new Date(item.timestamp).toLocaleString();
        const trxHtml = item.trx_id ? (' · trx: ' + (window.buildTrxLink ? window.buildTrxLink(item.trx_id) : '')) : '';
        const card = document.createElement('div');
        card.className = 'card border-secondary';
        const body = document.createElement('div');
        body.className = 'card-body py-2';
        const header = document.createElement('div');
        header.className = 'd-flex align-items-center gap-2 mb-1';
        const avatar = (window.createAvatarImg ? window.createAvatarImg(item.author, 24) : (function(){ const im=document.createElement('img'); im.src=`https://images.hive.blog/u/${authorSlug}/avatar`; im.alt=`@${author}`; im.width=24; im.height=24; im.loading='lazy'; im.className='rounded-circle flex-shrink-0'; im.style.objectFit='cover'; return im; })());
        const strong = document.createElement('strong');
        strong.className = 'mb-0';
        strong.style.fontSize = '0.95rem';
        strong.innerHTML = `<a href="/u/${authorSlug}">@${author}</a>`;
        header.appendChild(avatar);
        header.appendChild(strong);
        const meta = document.createElement('div');
        meta.className = 'small text-muted';
        meta.innerHTML = `${dtStr}${trxHtml}`;
        const contentDiv = document.createElement('div');
        contentDiv.className = 'card-text mt-1';
        contentDiv.innerHTML = item.html || linkify(item.content);
        body.appendChild(header);
        body.appendChild(meta);
        body.appendChild(contentDiv);
        card.appendChild(body);
        preview.innerHTML = '';
        preview.appendChild(card);
        preview.classList.remove('d-none');
      } catch (e) {
        // leave preview hidden on failure
      }
    })();
  }
  // Prefill with @author and focus caret
  if (replyAuthor) {
    const ta = document.getElementById("postContent");
    if (ta && !ta.value) {
      ta.value = `@${replyAuthor} `;
      ta.focus();
      // Move caret to end
      ta.selectionStart = ta.selectionEnd = ta.value.length;
    }
  }

  function updateCounter() {
    if (!ta || !counterEl) return;
    const len = (ta.value || '').length;
    counterEl.textContent = `${len} / ${MAX_LEN}`;
    if (len > MAX_LEN) {
      counterEl.classList.add('text-danger');
    } else {
      counterEl.classList.remove('text-danger');
    }
  }
  if (ta) {
    ta.addEventListener('input', updateCounter);
    updateCounter();
  }

  postForm.addEventListener("submit", function (e) {
    e.preventDefault();

    const content = ta.value;
    const username = localStorage.getItem("hive.username");

    if (!username) {
      if (window.showToast) showToast("Please login first", 'warning');
      return;
    }
    if ((content || '').length > MAX_LEN) {
      if (window.showToast) showToast(`Post is too long. Maximum ${MAX_LEN} characters.`, 'danger');
      return;
    }
    // Extract mentions and tags client-side
    function extractMentionsTags(text) {
      const mentions = new Set();
      const tags = new Set();
      // @mentions: hive usernames are lowercase letters, digits, and dashes
      const mRe = /(^|\s)@([a-z0-9\-\.]+)/gi;
      let m;
      while ((m = mRe.exec(text))) {
        const u = (m[2] || "").toLowerCase();
        if (u) mentions.add(u);
      }
      // #tags: lowercase letters, digits, dashes
      const tRe = /(^|\s)#([a-z0-9\-]+)/gi;
      let t;
      while ((t = tRe.exec(text))) {
        const tag = (t[2] || "").toLowerCase();
        if (tag) tags.add(tag);
      }
      return { mentions: Array.from(mentions), tags: Array.from(tags) };
    }

    const { mentions, tags } = extractMentionsTags(content || "");

    const payload = {
      app: appId,
      v: 1,
      type: "post",
      content: content,
      mentions: mentions,
      reply_to: replyTo,
      tags: tags,
    };

    if (!window.hive_keychain) {
      if (window.showToast) showToast("Hive Keychain not detected", 'warning');
      return;
    }

    const operations = [
      [
        "custom_json",
        {
          required_auths: [],
          required_posting_auths: [username],
          id: appId,
          json: JSON.stringify(payload),
        },
      ],
    ];

    window.hive_keychain.requestBroadcast(
      username,
      operations,
      "Posting",
      function (response) {
        console.log("Keychain broadcast response", response);
        if (response && response.success) {
          // Redirect to feed without popup; allow brief time for watcher ingestion
          setTimeout(() => (window.location.href = "/feed"), 300);
        } else {
          const msg = response && response.message ? response.message : "Unknown error";
          if (window.showToast) showToast("Error posting to Hive: " + msg, 'danger');
        }
      }
    );
  });
});
