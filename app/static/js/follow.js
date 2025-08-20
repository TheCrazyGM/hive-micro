document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('followBtn');
  if (!btn) return;

  async function handleClick() {
    try {
      const action = btn.getAttribute('data-action');
      const target = btn.getAttribute('data-target');
      const follower = localStorage.getItem('hive.username');
      if (!follower) {
        if (window.showToast) showToast('Please login first', 'warning');
        return;
      }
      if (!window.hive_keychain) {
        if (window.showToast) showToast('Hive Keychain not detected', 'warning');
        return;
      }

      btn.disabled = true;
      const followJson = JSON.stringify([
        'follow',
        {
          follower: follower,
          following: target,
          what: action === 'follow' ? ['blog'] : []
        }
      ]);
      const operations = [[
        'custom_json',
        {
          required_auths: [],
          required_posting_auths: [follower],
          id: 'follow',
          json: followJson
        }
      ]];
      window.hive_keychain.requestBroadcast(follower, operations, 'Posting', function (response) {
        btn.disabled = false;
        if (response && response.success) {
          if (action === 'follow') {
            btn.textContent = 'Unfollow';
            btn.setAttribute('data-action', 'unfollow');
            btn.className = 'btn btn-sm btn-outline-secondary';
            if (window.showToast) showToast(`Now following @${target}`, 'success');
          } else {
            btn.textContent = 'Follow';
            btn.setAttribute('data-action', 'follow');
            btn.className = 'btn btn-sm btn-primary';
            if (window.showToast) showToast(`Unfollowed @${target}`, 'info');
          }
        } else {
          const msg = response && response.message ? response.message : 'Unknown error';
          if (window.showToast) showToast('Follow action failed: ' + msg, 'danger');
        }
      });
    } catch (e) {
      btn.disabled = false;
      if (window.showToast) showToast('Follow action failed: ' + e.message, 'danger');
    }
  }

  btn.addEventListener('click', handleClick);
});

