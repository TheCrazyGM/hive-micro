document.addEventListener("DOMContentLoaded", () => {
  const feedContainer = document.getElementById("feed-container");
  const loadMoreBtn = document.getElementById("loadMoreBtn");
  const followingToggle = document.getElementById("followingToggle");
  const statusEl = document.getElementById("footer-status");
  const urlParams = new URLSearchParams(window.location.search);
  let currentTag = urlParams.get('tag');

  let cursor = null; // ISO string to paginate before
  let loading = false;

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
    // linkify @mentions -> /u/<username>
    const withMentions = esc.replace(/(^|\s)@([a-z0-9\-\.]+)/gi, (m, pre, u) => {
      const uname = encodeURIComponent(u.toLowerCase());
      return `${pre}<a href="/u/${uname}">@${u}</a>`;
    });
    // linkify #tags -> /feed?tag=<tag>
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

    const avatar = document.createElement('img');
    const author = escapeHTML(item.author);
    const authorSlug = encodeURIComponent(String(item.author).toLowerCase());
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
    p.innerHTML = item.html || linkify(item.content);

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
    rightWrap.className = 'meta-right d-flex align-items-center gap-2';
    const tagWrap = document.createElement("div");
    tagWrap.className = 'd-flex flex-wrap gap-1 mb-2';
    if (Array.isArray(item.tags) && item.tags.length) {
      for (const t of item.tags) {
        const a = document.createElement('a');
        a.href = `?tag=${encodeURIComponent(String(t).toLowerCase())}`;
        a.className = 'badge text-bg-light text-decoration-none';
        a.textContent = `#${t}`;
        tagWrap.appendChild(a);
      }
    }

    const replyBtn = document.createElement('button');
    replyBtn.type = 'button';
    replyBtn.className = 'btn btn-sm btn-outline-primary';
    replyBtn.textContent = 'Reply';
    if (item.trx_id) {
      replyBtn.addEventListener('click', () => {
        const url = `/new_post?reply_to=${encodeURIComponent(item.trx_id)}&author=${encodeURIComponent(item.author)}`;
        window.location.href = url;
      });
    } else {
      replyBtn.disabled = true;
      replyBtn.title = 'Reply unavailable';
    }

    rightWrap.appendChild(replyBtn);

    meta.appendChild(ts);
    meta.appendChild(rightWrap);

    body.appendChild(headerWrap);
    if (replyIndicator) body.appendChild(replyIndicator);
    body.appendChild(p);
    if (tagWrap.childElementCount) body.appendChild(tagWrap);
    body.appendChild(meta);
    card.appendChild(body);
    return card;
  }

  async function refreshStatus() {
    try {
      const res = await fetch("/api/v1/status");
      const data = await res.json();
      console.debug('[feed] timeline response', { status: res.status, count: data.count, items: (data.items||[]).length });
      if (statusEl) {
        statusEl.textContent = `app: ${data.app_id} · messages: ${data.messages} · last block: ${data.last_block}`;
      }
    } catch (e) {
      if (statusEl) {
        statusEl.textContent = "status unavailable";
      }
    }
  }

  // show active tag filter indicator
  function renderActiveTagIndicator() {
    let indicator = document.getElementById('activeTagIndicator');
    if (!currentTag) {
      if (indicator) indicator.remove();
      return;
    }
    if (!indicator) {
      indicator = document.createElement('div');
      indicator.id = 'activeTagIndicator';
      indicator.className = 'alert alert-info py-2 px-3 d-flex justify-content-between align-items-center';
      const parent = feedContainer.parentElement;
      parent.insertBefore(indicator, feedContainer);
    }
    indicator.innerHTML = `Filtering by tag <strong>#${currentTag}</strong> <button class="btn btn-sm btn-outline-secondary ms-2" id="clearTagBtn">Clear</button>`;
    const btn = indicator.querySelector('#clearTagBtn');
    btn.onclick = () => {
      const p = new URLSearchParams(window.location.search);
      p.delete('tag');
      window.location.search = p.toString();
    };
  }

  async function loadFeed(reset = false) {
    if (loading) return;
    loading = true;
    loadMoreBtn.disabled = true;

    if (reset) {
      feedContainer.innerHTML = "";
      cursor = null;
    }

    const params = new URLSearchParams();
    params.set("limit", "20");
    if (cursor) params.set("cursor", cursor);
    if (followingToggle.checked) params.set("following", "1");
    if (currentTag) params.set('tag', currentTag);
    console.debug('[feed] loadFeed', { reset, cursor, following: followingToggle.checked, tag: currentTag, qs: params.toString() });

    try {
      const res = await fetch(`/api/v1/timeline?${params.toString()}`);
      const data = await res.json();
      const items = data.items || [];
      for (const it of items) {
        const card = renderItem(it);
        feedContainer.appendChild(card);
      }
      if (items.length > 0) {
        cursor = items[items.length - 1].timestamp; // paginate by timestamp
        loadMoreBtn.disabled = false;
      } else {
        loadMoreBtn.disabled = true;
      }
    } catch (e) {
      console.error("Failed to load feed", e);
    } finally {
      loading = false;
    }
  }

  loadMoreBtn.addEventListener("click", () => loadFeed(false));
  followingToggle.addEventListener("change", () => {
    console.debug('[feed] followingToggle changed', { checked: followingToggle.checked });
    loadFeed(true);
    refreshStatus();
  });

  // initial load
  renderActiveTagIndicator();
  loadFeed(true);
  refreshStatus();
});
