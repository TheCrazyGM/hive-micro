document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('user-posts-container');
  const loadMoreBtn = document.getElementById('userPostsLoadMoreBtn');
  if (!container || !loadMoreBtn) return;

  const username = String(container.getAttribute('data-username') || '').trim();
  if (!username) {
    console.warn('[user_profile] Missing username');
    return;
  }

  let cursor = null; // ISO timestamp for pagination
  let loading = false;

  function renderItem(item) {
    const card = document.createElement('div');
    card.className = 'card mb-3';

    const body = document.createElement('div');
    body.className = 'card-body';

    const headerWrap = document.createElement('div');
    headerWrap.className = 'd-flex align-items-center gap-2 mb-1';

    const author = (window.escapeHTML ? window.escapeHTML(item.author) : String(item.author));
    const avatar = (window.createAvatarImg ? window.createAvatarImg(item.author, 32) : (function(){ const im=document.createElement('img'); const authorSlug = encodeURIComponent(String(item.author).toLowerCase()); im.src=`https://images.hive.blog/u/${authorSlug}/avatar`; im.alt=`@${author}`; im.width=32; im.height=32; im.loading='lazy'; im.className='rounded-circle flex-shrink-0'; im.style.objectFit='cover'; return im; })());
    const authorSlug = encodeURIComponent(String(item.author).toLowerCase());

    const h5 = document.createElement('h5');
    h5.className = 'card-title mb-0';
    h5.innerHTML = `<a href="/u/${authorSlug}">@${author}</a>`;

    headerWrap.appendChild(avatar);
    headerWrap.appendChild(h5);

    const p = document.createElement('p');
    p.className = 'card-text';
    p.innerHTML = item.html || (window.linkifyText ? window.linkifyText(item.content) : String(item.content));

    // In reply to indicator, if any
    let replyIndicator = window.buildReplyIndicator ? window.buildReplyIndicator(item.reply_to) : null;

    const meta = document.createElement('div');
    meta.className = 'post-meta d-flex justify-content-between align-items-center flex-nowrap gap-2';

    const ts = document.createElement('div');
    ts.className = 'text-muted meta-left';
    ts.style.fontSize = '0.8rem';
    const dtStr = new Date(item.timestamp).toLocaleString();
    if (item.trx_id) {
      const linkHtml = (window.buildTrxLink ? window.buildTrxLink(item.trx_id) : (function(){ const full=String(item.trx_id); const pid=encodeURIComponent(full); const short = `${full.slice(0,8)}…${full.slice(-8)}`; return `<a class="text-decoration-none" href="/p/${pid}" title="${full}"><code class=\"trx-hash\">${short}</code></a>`; })());
      ts.innerHTML = `${dtStr} · trx: ${linkHtml}`;
    } else {
      ts.textContent = dtStr;
    }

    const rightWrap = document.createElement('div');
    rightWrap.className = 'meta-right d-flex align-items-center gap-2';
    const tagWrap = (window.buildTagChips ? window.buildTagChips(item.tags || [], { basePath: '/feed?tag=', itemClass: 'badge tag-chip text-decoration-none' }) : (function(){ const d=document.createElement('div'); d.className='d-flex flex-wrap gap-1 mb-2'; return d; })());

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

  async function loadPosts(reset = false) {
    if (loading) return;
    loading = true;
    loadMoreBtn.disabled = true;

    if (reset) {
      container.innerHTML = '';
      cursor = null;
    }

    const params = new URLSearchParams();
    params.set('limit', '20');
    params.set('author', username);
    if (cursor) params.set('cursor', cursor);

    try {
      const res = await fetch(`/api/v1/timeline?${params.toString()}`);
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
    } catch (e) {
      console.error('[user_profile] Failed to load posts', e);
    } finally {
      loading = false;
    }
  }

  loadMoreBtn.addEventListener('click', () => loadPosts(false));

  // Initial load
  loadPosts(true);
});
