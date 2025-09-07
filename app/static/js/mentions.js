document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("mentions-container");
  const loadMoreBtn = document.getElementById("mentionsLoadMoreBtn");

  let cursor = null; // ISO string to paginate before
  let loading = false;

  async function markSeen() {
    try {
      const csrf = (window.getCsrfToken ? window.getCsrfToken() : (document.querySelector('meta[name="csrf-token"]')?.content || window.CSRF_TOKEN || ''));
      await fetch('/api/v1/mentions/seen', { method: 'POST', headers: { 'X-CSRF-Token': csrf } });
      if (window.setMentionBadge) setMentionBadge(0);
    } catch (e) {}
  }

  function escapeHTML(s) { return window.escapeHTML ? window.escapeHTML(s) : String(s); }

  function linkify(text) { return window.linkifyText ? window.linkifyText(text) : String(text || ''); }

  async function renderItem(item) {
    const card = document.createElement("div");
    card.className = "card mb-3";

    const body = document.createElement("div");
    body.className = "card-body";

    const headerWrap = document.createElement('div');
    headerWrap.className = 'd-flex align-items-center gap-2 mb-1';
    const author = escapeHTML(item.author);
    const authorSlug = encodeURIComponent(String(item.author).toLowerCase());
    const avatar = (window.createAvatarImg ? window.createAvatarImg(item.author, 32) : (function(){ const im=document.createElement('img'); im.src=`https://images.hive.blog/u/${authorSlug}/avatar`; im.alt=`@${author}`; im.width=32; im.height=32; im.loading='lazy'; im.className='rounded-circle flex-shrink-0'; im.style.objectFit='cover'; return im; })());
    const h5 = document.createElement("h5");
    h5.className = "card-title mb-0";
    h5.innerHTML = `<a href="/u/${authorSlug}">@${author}</a>`;
    headerWrap.appendChild(avatar);
    headerWrap.appendChild(h5);

    const p = document.createElement("p");
    p.className = "card-text";
    p.innerHTML = linkify(item.content);

    // In reply to indicator (async)
    let replyIndicator = window.buildReplyIndicator ? await window.buildReplyIndicator(item.reply_to) : null;

    const meta = document.createElement("div");
    meta.className = "post-meta d-flex justify-content-between align-items-center flex-nowrap gap-2";

    const ts = document.createElement("div");
    ts.className = "text-muted meta-left";
    ts.style.fontSize = "0.8rem";
    const dtStr = new Date(item.timestamp).toLocaleString();
    if (item.trx_id) {
      const linkHtml = (window.buildTrxLink ? window.buildTrxLink(item.trx_id) : (function(){ const full=String(item.trx_id); const pid=encodeURIComponent(full); const short = `${full.slice(0,8)}…${full.slice(-8)}`; return `<a class=\"text-decoration-none\" href=\"/p/${pid}\" title=\"${full}\"><code class=\"trx-hash\">${short}</code></a>`; })());
      ts.innerHTML = `${dtStr} · trx: ${linkHtml}`;
    } else {
      ts.textContent = dtStr;
    }

    const rightWrap = document.createElement('div');
    rightWrap.className = 'd-flex align-items-center gap-2';
    const tagWrap = (window.buildTagChips ? window.buildTagChips(item.tags || [], { basePath: '/feed?tag=', itemClass: 'badge tag-chip text-decoration-none', extraItemClass: 'me-1' }) : (function(){ const d=document.createElement('div'); d.className='d-flex flex-wrap gap-1 mb-2'; return d; })());

    // Heart (appreciation) button
    const heartBtn = document.createElement('button');
    heartBtn.type = 'button';
    heartBtn.className = item.viewer_hearted ? 'btn btn-sm btn-danger' : 'btn btn-sm btn-outline-danger';
    const updateHeartBtn = (count, on) => {
      heartBtn.className = on ? 'btn btn-sm btn-danger' : 'btn btn-sm btn-outline-danger';
      heartBtn.innerHTML = `❤ <span class="ms-1">${typeof count === 'number' ? count : 0}</span>`;
    };
    updateHeartBtn(item.hearts, !!item.viewer_hearted);
    heartBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      e.preventDefault();
      try {
        const csrf = (window.getCsrfToken ? window.getCsrfToken() : (document.querySelector('meta[name="csrf-token"]')?.content || window.CSRF_TOKEN || ''));
        const url = item.viewer_hearted ? '/api/v1/unheart' : '/api/v1/heart';
        const r = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
          body: JSON.stringify({ trx_id: item.trx_id })
        });
        const d = await r.json().catch(()=>({ success:false }));
        if (!r.ok || d.success !== true) throw new Error(d.error || 'Request failed');
        item.viewer_hearted = !!d.viewer_hearted;
        item.hearts = typeof d.hearts === 'number' ? d.hearts : item.hearts;
        updateHeartBtn(item.hearts, item.viewer_hearted);
      } catch (err) {
        if (window.showToast) showToast('Failed to update heart: ' + err.message, 'danger');
      }
    });

    const replyBtn = document.createElement('button');
    replyBtn.type = 'button';
    replyBtn.className = 'btn btn-sm btn-outline-primary';
    replyBtn.textContent = 'Reply';
    replyBtn.addEventListener('click', () => {
      const url = `/new_post?reply_to=${encodeURIComponent(item.trx_id)}&author=${encodeURIComponent(item.author)}`;
      window.location.href = url;
    });

    rightWrap.appendChild(tagWrap);
    rightWrap.appendChild(heartBtn);
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
        const card = await renderItem(it);
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
