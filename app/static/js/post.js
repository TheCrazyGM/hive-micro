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
        const shortTrx = item.trx_id ? `${escapeHTML(String(item.trx_id).slice(0,8))}…${escapeHTML(String(item.trx_id).slice(-8))}` : '';
        const trxHtml = item.trx_id ? ` · trx: <a class="text-decoration-none" href="/p/${encodeURIComponent(item.trx_id)}" title="${escapeHTML(item.trx_id)}"><code class="trx-hash">${shortTrx}</code></a>` : '';
        const html = `
          <div class="card border-secondary">
            <div class="card-body py-2">
              <div class="d-flex align-items-center gap-2 mb-1">
                <img src="https://images.hive.blog/u/${authorSlug}/avatar" alt="@${author}" width="24" height="24" class="rounded-circle flex-shrink-0" style="object-fit:cover;" loading="lazy" />
                <strong class="mb-0" style="font-size:0.95rem;"><a href="/u/${authorSlug}">@${author}</a></strong>
              </div>
              <div class="small text-muted">${dtStr}${trxHtml}</div>
              <div class="card-text mt-1">${item.html || linkify(item.content)}</div>
            </div>
          </div>`;
        preview.innerHTML = html;
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
