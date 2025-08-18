document.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('post-view');
  const trxId = root?.getAttribute('data-trx-id');
  if (!trxId) {
    root.textContent = 'Missing post id';
    return;
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

  function renderCard(item, isParent = false) {
    const card = document.createElement('div');
    card.className = `card mb-3 ${isParent ? 'border-primary' : ''}`;

    const body = document.createElement('div');
    body.className = 'card-body';

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

    const h5 = document.createElement('h5');
    h5.className = 'card-title mb-0';
    h5.innerHTML = `<a href="/u/${authorSlug}">@${author}</a>`;

    headerWrap.appendChild(avatar);
    headerWrap.appendChild(h5);

    if (item.reply_to) {
      const replyIndicator = document.createElement('div');
      replyIndicator.className = 'reply-indicator small mb-1';
      replyIndicator.innerHTML = `in reply to <a href="/p/${encodeURIComponent(item.reply_to)}">parent</a>`;
      body.appendChild(replyIndicator);
    }

    const p = document.createElement('p');
    p.className = 'card-text';
    p.innerHTML = item.html || linkify(item.content);

    const meta = document.createElement('div');
    meta.className = 'post-meta d-flex justify-content-between align-items-center flex-nowrap gap-2';

    const ts = document.createElement('div');
    ts.className = 'text-muted meta-left';
    ts.style.fontSize = '0.8rem';
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

    const tagsWrap = document.createElement('div');
    tagsWrap.className = 'd-flex flex-wrap gap-1 mb-2';
    if (Array.isArray(item.tags) && item.tags.length) {
      for (const t of item.tags) {
        const a = document.createElement('a');
        a.href = `/feed?tag=${encodeURIComponent(String(t).toLowerCase())}`;
        a.className = 'badge text-bg-light text-decoration-none';
        a.textContent = `#${t}`;
        tagsWrap.appendChild(a);
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
    body.appendChild(p);
    if (tagsWrap.childElementCount) body.appendChild(tagsWrap);
    body.appendChild(meta);
    card.appendChild(body);
    return card;
  }

  async function load() {
    root.innerHTML = '<div class="text-center text-muted">Loading…</div>';
    try {
      const res = await fetch(`/api/v1/post/${encodeURIComponent(trxId)}`);
      if (!res.ok) {
        root.innerHTML = `<div class="alert alert-danger">Error loading post (${res.status})</div>`;
        return;
      }
      const data = await res.json();
      root.innerHTML = '';

      const parentCard = renderCard(data.item, true);
      root.appendChild(parentCard);

      const replies = Array.isArray(data.replies) ? data.replies : [];
      if (replies.length) {
        const h = document.createElement('h6');
        h.className = 'mt-3 mb-2';
        h.textContent = 'Replies';
        root.appendChild(h);
        for (const r of replies) {
          const rc = renderCard(r, false);
          root.appendChild(rc);
        }
      }
    } catch (e) {
      root.innerHTML = `<div class="alert alert-danger">Failed to load post</div>`;
    }
  }

  load();
});
