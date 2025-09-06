document.addEventListener('DOMContentLoaded', () => {
  const auditTableBody = document.getElementById('auditTableBody');
  const loadMoreBtn = document.getElementById('loadMoreBtn');
  const refreshBtn = document.getElementById('refreshBtn');
  const statusFilter = document.getElementById('statusFilter');

  let cursor = null;
  let loading = false;
  let currentFilter = 'all';

  function renderModeratedPost(item) {
    const row = document.createElement('tr');

    // When moderated: prefer mod_at (final moderation record),
    // for pending use last_action_at from latest hide action
    const whenCell = document.createElement('td');
    whenCell.className = 'small text-muted';
    const whenIso = item.mod_at || item.last_action_at || null;
    if (whenIso) {
      const modTime = new Date(whenIso);
      const label = isNaN(modTime.getTime()) ? whenIso : modTime.toLocaleString();
      whenCell.innerHTML = `<time class="ts-local" datetime="${whenIso}">${label}</time>`;
    } else {
      whenCell.textContent = '—';
    }
    row.appendChild(whenCell);

    // Moderator
    const modCell = document.createElement('td');
    modCell.className = 'small';
    const isHidden = !!item.hidden;
    const isPending = !!item.pending;
    if (isHidden && item.mod_by) {
      modCell.innerHTML = `<a href="/u/${item.mod_by}" class="text-decoration-none">@${item.mod_by}</a>`;
    } else if (isPending && Array.isArray(item.approvers) && item.approvers.length) {
      const first = item.approvers[0];
      const more = item.approvers.length - 1;
      const moreTxt = more > 0 ? ` +${more}` : '';
      modCell.innerHTML = `<a href="/u/${first}" class="text-decoration-none">@${first}</a>${moreTxt}`;
      modCell.title = `Approvals: ${item.approvers.map(a=>`@${a}`).join(', ')}`;
    } else {
      modCell.textContent = '—';
    }
    row.appendChild(modCell);

    // Author
    const authorCell = document.createElement('td');
    authorCell.className = 'small';
    authorCell.innerHTML = `<a href="/u/${item.author}" class="text-decoration-none">@${item.author}</a>`;
    row.appendChild(authorCell);

    // Content (truncated)
    const contentCell = document.createElement('td');
    const content = (item.content || '').substring(0, 100);
    const truncated = item.content && item.content.length > 100 ? content + '...' : content;
    contentCell.className = 'small';
    contentCell.innerHTML = `<div class="text-truncate" style="max-width: 200px;" title="${item.content || ''}">${truncated || '<em>No content</em>'}</div>`;
    row.appendChild(contentCell);

    // Reason: prefer mod_reason for hidden; for pending, use last_reason from latest hide action
    const reasonCell = document.createElement('td');
    reasonCell.className = 'small';
    const reason = (isHidden ? item.mod_reason : (isPending ? item.last_reason : item.mod_reason)) || '';
    if (reason) {
      const short = reason.substring(0, 50) + (reason.length > 50 ? '...' : '');
      reasonCell.innerHTML = `<span title="${reason}">${short}</span>`;
    } else {
      reasonCell.innerHTML = '<em>No reason provided</em>';
    }
    row.appendChild(reasonCell);

    // Status
    const statusCell = document.createElement('td');
    let badge = '<span class="badge text-bg-secondary">Public</span>';
    if (isHidden) badge = '<span class="badge text-bg-danger">Hidden</span>';
    else if (isPending) badge = '<span class="badge text-bg-warning">Pending</span>';
    statusCell.innerHTML = badge;
    row.appendChild(statusCell);

    // Action (link to post)
    const actionCell = document.createElement('td');
    actionCell.innerHTML = `<a href="/p/${item.trx_id}" class="btn btn-sm btn-outline-primary" target="_blank">View Post</a>`;
    row.appendChild(actionCell);

    return row;
  }

  async function loadAuditData(reset = false) {
    if (loading) return;
    loading = true;
    loadMoreBtn.disabled = true;

    if (reset) {
      auditTableBody.innerHTML = '';
      cursor = null;
    }

    const params = new URLSearchParams();
    params.set('limit', '20');
    if (cursor) params.set('cursor', cursor);
    if (currentFilter === 'hidden') {
      params.set('status', 'hidden');
    } else {
      params.set('status', 'all');
    }

    try {
      const response = await fetch(`/api/v1/mod/audit?${params.toString()}`);
      if (!response.ok) {
        throw new Error('Failed to load audit data');
      }

      const data = await response.json();
      const items = data.items || [];

      if (items.length === 0 && reset) {
        auditTableBody.innerHTML = '<tr><td class="text-muted" colspan="7">No moderated content found</td></tr>';
        loadMoreBtn.style.display = 'none';
        return;
      }

      for (const item of items) {
        const row = renderModeratedPost(item);
        auditTableBody.appendChild(row);
      }

      if (items.length > 0) {
        cursor = items[items.length - 1].timestamp;
        loadMoreBtn.disabled = false;
      } else {
        loadMoreBtn.style.display = 'none';
      }
    } catch (error) {
      console.error('Error loading audit data:', error);
      if (reset) {
        auditTableBody.innerHTML = '<tr><td class="text-danger" colspan="7">Failed to load moderation audit data</td></tr>';
      }
    } finally {
      loading = false;
    }
  }

  // Event listeners
  loadMoreBtn.addEventListener('click', () => loadAuditData(false));
  refreshBtn.addEventListener('click', () => loadAuditData(true));
  statusFilter.addEventListener('change', () => {
    currentFilter = statusFilter.value;
    loadAuditData(true);
  });

  // Initial load
  loadAuditData(true);
});
