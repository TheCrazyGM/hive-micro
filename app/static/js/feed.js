document.addEventListener("DOMContentLoaded", () => {
  const feedContainer = document.getElementById("feed-container");
  const loadMoreBtn = document.getElementById("loadMoreBtn");
  const followingToggle = document.getElementById("followingToggle");
  const statusEl = document.getElementById("footer-status");
  const newBanner = document.getElementById('newPostsBanner');
  const newCountEl = document.getElementById('newPostsCount');
  const showNewBtn = document.getElementById('showNewPostsBtn');
  const dismissNewBtn = document.getElementById('dismissNewPostsBtn');
  const navFeedBadge = document.getElementById('nav-feed-new-count');
  const trendingList = document.getElementById('trendingTagsList');
  const refreshTrendingBtn = document.getElementById('refreshTrendingBtn');
  const modShowHiddenToggle = document.getElementById('modShowHiddenToggle');
  const urlParams = new URLSearchParams(window.location.search);
  let currentTag = urlParams.get('tag');

  let cursor = null; // ISO string to paginate before
  let loading = false;
  let latestTopTs = null; // most recent item timestamp currently shown

  // ---- Persisted preferences (localStorage) ----
  const LS_FOLLOWING_KEY = 'hive.followingOnly';
  const LS_SHOW_HIDDEN_KEY = 'hive.showHidden';
  function loadFollowingPref() {
    try {
      const v = localStorage.getItem(LS_FOLLOWING_KEY);
      const on = v === '1' || v === 'true';
      followingToggle.checked = !!on;
    } catch (_) {
      // ignore storage errors
    }
  }
  function saveFollowingPref() {
    try {
      localStorage.setItem(LS_FOLLOWING_KEY, followingToggle.checked ? '1' : '0');
    } catch (_) {
      // ignore storage errors
    }
  }

  function loadShowHiddenPref() {
    if (!modShowHiddenToggle) return;
    try {
      const v = localStorage.getItem(LS_SHOW_HIDDEN_KEY);
      modShowHiddenToggle.checked = (v === '1' || v === 'true');
    } catch (_) {}
  }
  function saveShowHiddenPref() {
    if (!modShowHiddenToggle) return;
    try { localStorage.setItem(LS_SHOW_HIDDEN_KEY, modShowHiddenToggle.checked ? '1' : '0'); } catch (_) {}
  }

  function escapeHTML(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  async function loadTrendingTags() {
    if (!trendingList) return;
    // If list already has content, avoid flicker: dim while refreshing.
    const state = trendingList.getAttribute('data-state') || '';
    const hasRendered = state === 'ready' || state === 'empty';
    try {
      if (hasRendered) {
        trendingList.style.transition = 'opacity .25s ease';
        trendingList.classList.add('opacity-50');
      } else {
        trendingList.innerHTML = '<li class="list-group-item text-muted">Loading…</li>';
        trendingList.setAttribute('data-state', 'placeholder');
      }
      const p = new URLSearchParams();
      p.set('limit', '15');
      const res = await fetch(`/api/v1/tags/trending?${p.toString()}`);
      const data = await res.json();
      const items = data.items || [];
      if (!items.length) {
        trendingList.innerHTML = '<li class="list-group-item text-muted">No trending tags</li>';
        trendingList.setAttribute('data-state', 'empty');
        trendingList.classList.remove('opacity-50');
        return;
      }
      trendingList.innerHTML = '';
      for (const it of items) {
        const li = document.createElement('li');
        li.className = 'list-group-item d-flex justify-content-between align-items-center';
        const tag = String(it.tag || '').toLowerCase();
        li.innerHTML = `<a href="/feed?tag=${encodeURIComponent(tag)}">#${escapeHTML(tag)}</a><span class="badge text-bg-secondary">${it.count || 0}</span>`;
        trendingList.appendChild(li);
      }
      trendingList.setAttribute('data-state', 'ready');
      trendingList.classList.remove('opacity-50');
    } catch (e) {
      // On error, keep existing content to avoid flicker; if nothing rendered yet, show error once.
      if (!hasRendered) {
        trendingList.innerHTML = '<li class="list-group-item text-danger">Failed to load</li>';
        trendingList.setAttribute('data-state', 'empty');
      }
      trendingList.classList.remove('opacity-50');
    }
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
        a.className = 'badge tag-chip text-decoration-none';
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
    if (window.HIVE_IS_MOD && item.hidden) {
      const badge = document.createElement('span');
      badge.className = 'badge text-bg-warning';
      badge.textContent = 'Hidden';
      rightWrap.appendChild(badge);
    }
    if (window.HIVE_IS_MOD) {
      const modBtn = document.createElement('button');
      modBtn.type = 'button';
      if (item.hidden) {
        modBtn.className = 'btn btn-sm btn-success';
        modBtn.textContent = 'Unhide';
      } else {
        modBtn.className = 'btn btn-sm btn-outline-danger';
        modBtn.textContent = 'Hide';
      }
      modBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        e.preventDefault();
        try {
          const csrf = (window.getCsrfToken ? window.getCsrfToken() : (document.querySelector('meta[name="csrf-token"]')?.content || window.CSRF_TOKEN || ''));
          if (item.hidden) {
            // Unhide flow
            const payload = { trx_id: item.trx_id };
            if (window.requestModerationSignature) {
              const sig = await window.requestModerationSignature('unhide', item.trx_id);
              if (sig === null) return; Object.assign(payload, sig);
            }
            const r = await fetch('/api/v1/mod/unhide', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify(payload) });
            const d = await r.json().catch(()=>({}));
            if (!r.ok || !d.success) throw new Error(d.error || 'Request failed');
            if (window.showToast) showToast('Post unhidden', 'success');
            card.remove();
          } else {
            // Hide flow
            const payload = { trx_id: item.trx_id };
            if (window.HIVE_MOD_REASON_REQUIRED && window.showReasonModal) {
              const rsn = await showReasonModal({ title: 'Reason to hide', required: true });
              if (rsn == null) return; payload.reason = rsn;
            }
            if (window.requestModerationSignature) {
              const sig = await window.requestModerationSignature('hide', item.trx_id);
              if (sig === null) return; Object.assign(payload, sig);
            }
            const r = await fetch('/api/v1/mod/hide', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify(payload) });
            const d = await r.json().catch(() => ({}));
            if (!r.ok || !d.success) throw new Error(d.error || 'Request failed');
            if (d.hidden) {
              if (window.showToast) showToast('Post hidden', 'success');
              card.remove();
            } else if (typeof d.approvals === 'number' && typeof d.quorum === 'number') {
              if (window.showToast) showToast(`Pending: ${d.approvals}/${d.quorum} approvals`, 'info');
            } else {
              if (window.showToast) showToast('Hide recorded', 'info');
            }
          }
        } catch (err) {
          if (window.showToast) showToast('Failed to hide: ' + err.message, 'danger');
        }
      });
      rightWrap.appendChild(modBtn);
    }

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
    if (window.HIVE_IS_MOD && modShowHiddenToggle && modShowHiddenToggle.checked) {
      params.set('include_hidden', '1');
    }
    console.debug('[feed] loadFeed', { reset, cursor, following: followingToggle.checked, tag: currentTag, qs: params.toString() });

    try {
      const res = await fetch(`/api/v1/timeline?${params.toString()}`);
      const data = await res.json();
      const items = data.items || [];
      if (reset && items.length > 0) {
        latestTopTs = items[0].timestamp;
      }
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

  function updateNewUI(count) {
    // Banner
    if (newBanner && newCountEl) {
      if (count > 0) {
        newCountEl.textContent = count;
        newBanner.classList.remove('d-none');
      } else {
        newBanner.classList.add('d-none');
      }
    }
    // Navbar badge
    if (navFeedBadge) {
      if (count > 0) {
        navFeedBadge.textContent = count;
        navFeedBadge.classList.remove('d-none');
        navFeedBadge.className = 'badge text-bg-primary';
      } else {
        navFeedBadge.textContent = '0';
        navFeedBadge.classList.add('d-none');
        navFeedBadge.className = 'badge text-bg-secondary d-none';
      }
    }
  }

  async function pollNewCount() {
    // If we don't yet have a top timestamp, nothing to compare against
    if (!latestTopTs) return;
    try {
      const p = new URLSearchParams();
      p.set('since', latestTopTs);
      if (followingToggle.checked) p.set('following', '1');
      if (window.HIVE_IS_MOD && modShowHiddenToggle && modShowHiddenToggle.checked) {
        p.set('include_hidden', '1');
      }
      if (currentTag) p.set('tag', currentTag);
      const r = await fetch(`/api/v1/timeline/new_count?${p.toString()}`);
      if (!r.ok) throw new Error('bad');
      const d = await r.json();
      updateNewUI(d.count || 0);
    } catch (e) {
      // On error, hide banner but keep badge state unchanged
      updateNewUI(0);
    }
  }

  if (showNewBtn) {
    showNewBtn.addEventListener('click', async () => {
      // Reload feed from top
      await loadFeed(true);
      updateNewUI(0);
    });
  }
  if (dismissNewBtn) {
    dismissNewBtn.addEventListener('click', () => updateNewUI(0));
  }

  if (refreshTrendingBtn) {
    refreshTrendingBtn.addEventListener('click', () => loadTrendingTags());
  }

  loadMoreBtn.addEventListener("click", () => loadFeed(false));
  followingToggle.addEventListener("change", () => {
    console.debug('[feed] followingToggle changed', { checked: followingToggle.checked });
    saveFollowingPref();
    loadFeed(true);
    refreshStatus();
  });
  if (modShowHiddenToggle) {
    modShowHiddenToggle.addEventListener('change', () => {
      saveShowHiddenPref();
      loadFeed(true);
    });
  }

  // initial load
  renderActiveTagIndicator();
  // initialize following toggle from storage BEFORE first load
  loadFollowingPref();
  loadShowHiddenPref();
  loadFeed(true);
  loadTrendingTags();
  refreshStatus();
  // poll for new posts every 20s
  setInterval(pollNewCount, 20000);
  // refresh trending tags every 60s
  setInterval(loadTrendingTags, 60000);
})
;
