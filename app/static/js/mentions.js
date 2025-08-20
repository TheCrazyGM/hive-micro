document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("mentions-container");
  const loadMoreBtn = document.getElementById("mentionsLoadMoreBtn");

  let cursor = null; // ISO string to paginate before
  let loading = false;

  async function markSeen() {
    try {
      await fetch('/api/v1/mentions/seen', { method: 'POST' });
      // Optimistically update navbar badge if present
      const badge = document.getElementById('nav-mentions-count');
      if (badge) {
        badge.textContent = '0';
        badge.className = 'badge text-bg-secondary';
      }
    } catch (e) {
      // ignore
    }
  }

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

  function renderItem(item) {
    const card = document.createElement("div");
    card.className = "card mb-3";

    const body = document.createElement("div");
    body.className = "card-body";

    const headerWrap = document.createElement('div');
    headerWrap.className = 'd-flex align-items-center gap-2 mb-1';
    const author = escapeHTML(item.author);
    const authorSlug = encodeURIComponent(String(item.author).toLowerCase());
    const avatar = document.createElement('img');
    avatar.src = `https://images.hive.blog/u/${authorSlug}/avatar`;
    avatar.alt = `@${author}`;
    avatar.width = 32;
    avatar.height = 32;
    avatar.loading = 'lazy';
    avatar.className = 'rounded-circle flex-shrink-0';
    avatar.style.objectFit = 'cover';
    const h5 = document.createElement("h5");
    h5.className = "card-title mb-0";
    h5.innerHTML = `<a href="/u/${authorSlug}">@${author}</a>`;
    headerWrap.appendChild(avatar);
    headerWrap.appendChild(h5);

    const p = document.createElement("p");
    p.className = "card-text";
    p.innerHTML = linkify(item.content);

    // In reply to indicator
    let replyIndicator = null;
    if (item.reply_to) {
      replyIndicator = document.createElement('div');
      replyIndicator.className = 'reply-indicator small mb-1';
      const parentLink = `/p/${encodeURIComponent(item.reply_to)}`;
      replyIndicator.innerHTML = `in reply to <a href="${parentLink}">parent</a>`;
    }

    const meta = document.createElement("div");
    meta.className = "post-meta d-flex justify-content-between align-items-center flex-nowrap gap-2";

    const ts = document.createElement("div");
    ts.className = "text-muted meta-left";
    ts.style.fontSize = "0.8rem";
    const dtStr = new Date(item.timestamp).toLocaleString();
    if (item.trx_id) {
      const pid = encodeURIComponent(item.trx_id);
      const full = String(item.trx_id);
      const short = `${escapeHTML(full.slice(0, 8))}…${escapeHTML(full.slice(-8))}`;
      ts.innerHTML = `${dtStr} · trx: <a class="text-decoration-none" href="/p/${pid}" title="${escapeHTML(full)}"><code class="trx-hash">${short}</code></a>`;
    } else {
      ts.textContent = dtStr;
    }

    const rightWrap = document.createElement('div');
    rightWrap.className = 'd-flex align-items-center gap-2';
    const tagWrap = document.createElement("div");
    if (Array.isArray(item.tags) && item.tags.length) {
      for (const t of item.tags) {
        const a = document.createElement('a');
        a.href = `/feed?tag=${encodeURIComponent(String(t).toLowerCase())}`;
        a.className = 'badge tag-chip text-decoration-none me-1';
        a.textContent = `#${t}`;
        tagWrap.appendChild(a);
      }
    }

    const replyBtn = document.createElement('button');
    replyBtn.type = 'button';
    replyBtn.className = 'btn btn-sm btn-outline-primary';
    replyBtn.textContent = 'Reply';
    replyBtn.addEventListener('click', () => {
      const url = `/new_post?reply_to=${encodeURIComponent(item.trx_id)}&author=${encodeURIComponent(item.author)}`;
      window.location.href = url;
    });

    rightWrap.appendChild(tagWrap);
    rightWrap.appendChild(replyBtn);

    meta.appendChild(ts);
    meta.appendChild(rightWrap);

    body.appendChild(headerWrap);
    if (replyIndicator) body.appendChild(replyIndicator);
    body.appendChild(p);
    body.appendChild(meta);
    card.appendChild(body);
    return card;
  }

  async function load(reset = false) {
    if (loading) return;
    loading = true;
    loadMoreBtn.disabled = true;

    if (reset) {
      container.innerHTML = "";
      cursor = null;
    }

    const params = new URLSearchParams();
    params.set("limit", "20");
    if (cursor) params.set("cursor", cursor);

    try {
      const res = await fetch(`/api/v1/mentions?${params.toString()}`);
      const data = await res.json();
      const items = data.items || [];
      for (const it of items) {
        const card = renderItem(it);
        container.appendChild(card);
      }
      if (items.length > 0) {
        cursor = items[items.length - 1].timestamp;
        loadMoreBtn.disabled = false;
      } else {
        loadMoreBtn.disabled = true;
      }
      // After rendering, mark as seen
      markSeen();
    } catch (e) {
      console.error("Failed to load mentions", e);
    } finally {
      loading = false;
    }
  }

  loadMoreBtn.addEventListener("click", () => load(false));
  // Also mark seen when tab becomes visible
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      markSeen();
    }
  });

  window.addEventListener('focus', () => markSeen());

  load(true);
});
