(function(){
  function byId(id){ return document.getElementById(id); }
  function setTipStatus(msg, type){
    const el = byId('tipStatus');
    if (!el) return;
    el.textContent = msg || '';
    el.className = 'small ' + (type === 'error' ? 'text-danger' : type === 'success' ? 'text-success' : 'text-muted');
  }
  function populateTokens(){
    try{
      const sel = byId('tipToken');
      if (!sel) return;
      sel.innerHTML = '';
      const tokens = Array.isArray(window.HIVE_TIP_TOKENS) ? window.HIVE_TIP_TOKENS : ['HIVE','HBD'];
      tokens.forEach(t => {
        const opt = document.createElement('option');
        opt.value = String(t).toUpperCase();
        opt.textContent = String(t).toUpperCase();
        sel.appendChild(opt);
      });
      // All transfers require Active key; show a consistent hint
      function updateHint(){
        try { setTipStatus('Transfer requires Active key (Keychain will prompt).', ''); } catch(_) {}
      }
      sel.addEventListener('change', updateHint);
      updateHint();
    }catch(_){ }
  }
  function openTipModal(recipient){
    try{
      const uname = String(recipient || '').replace(/^@/, '');
      const recEl = byId('tipRecipient');
      const memoEl = byId('tipMemo');
      const amtEl = byId('tipAmount');
      if (recEl) recEl.value = uname;
      if (memoEl) memoEl.value = (window.HIVE_TIP_MEMO_PREFIX || (window.HIVE_APP_ID ? (window.HIVE_APP_ID + ' tip') : 'tip'));
      if (amtEl) { amtEl.step = '0.001'; amtEl.min = '0.001'; if (!amtEl.value) amtEl.value = '0.001'; }
      populateTokens();
      setTipStatus('', '');
      const el = byId('tipModal');
      if (!el) return;
      const modal = new bootstrap.Modal(el);
      el.__modalInstance = modal;
      modal.show();
    }catch(_){ }
  }
  async function sendTip(){
    try{
      const username = localStorage.getItem('hive.username');
      if (!username) { if (window.showToast) showToast('Please login first', 'warning'); return; }
      if (!window.hive_keychain) { if (window.showToast) showToast('Hive Keychain not detected', 'warning'); return; }
      const to = (byId('tipRecipient')?.value || '').trim().toLowerCase();
      const rawAmt = parseFloat(byId('tipAmount')?.value || '0');
      const sym = (byId('tipToken')?.value || 'HIVE').toUpperCase();
      const memo = byId('tipMemo')?.value || '';
      if (!to) { setTipStatus('Recipient missing', 'error'); return; }
      if (!rawAmt || rawAmt <= 0) { setTipStatus('Amount must be > 0', 'error'); return; }
      // Quantity formatting: 3 decimals per requirement
      const amt = rawAmt.toFixed(3);
      setTipStatus('Requesting Keychain (Active)…', '');
      if (sym === 'HIVE' || sym === 'HBD'){
        // Native transfer
        window.hive_keychain.requestTransfer(username, to, amt, memo, sym, function(res){
          if (res && res.success){
            setTipStatus('Tip sent', 'success');
            if (window.showToast) showToast('Tip sent', 'success');
            const m = byId('tipModal'); if (m && m.__modalInstance) m.__modalInstance.hide();
          } else {
            const msg = res && res.message ? res.message : 'Transfer failed';
            setTipStatus(msg, 'error');
            if (window.showToast) showToast(msg, 'danger');
          }
        });
      } else {
        // Hive-Engine token transfer via custom_json id ssc-mainnet-hive
        const payload = {
          contractName: 'tokens',
          contractAction: 'transfer',
          contractPayload: {
            symbol: sym,
            to: to,
            quantity: amt,
            memo: memo || ''
          }
        };
        const jsonStr = JSON.stringify(payload);
        // Active key is required for Hive-Engine transfers
        window.hive_keychain.requestCustomJson(
          username,
          'ssc-mainnet-hive',
          'Active',
          jsonStr,
          'Send HE tip',
          function(res){
            if (res && res.success){
              setTipStatus('Tip sent', 'success');
              if (window.showToast) showToast('Tip sent', 'success');
              const m = byId('tipModal'); if (m && m.__modalInstance) m.__modalInstance.hide();
            } else {
              const msg = res && res.message ? res.message : 'Custom JSON failed';
              setTipStatus(msg, 'error');
              if (window.showToast) showToast(msg, 'danger');
            }
          }
        );
      }
    }
    catch (e){
      setTipStatus(e && e.message ? e.message : 'Failed', 'error');
    }
  }

  function hookGlobal(){
    const sendBtn = byId('tipSendBtn');
    // Open modal on any .tip-btn click
    document.addEventListener('click', function(ev){
      try{
        const btn = ev.target.closest('.tip-btn');
        if (!btn) return;
        ev.preventDefault();
        const rec = btn.getAttribute('data-recipient') || btn.getAttribute('data-author') || btn.getAttribute('data-username') || '';
        openTipModal(rec);
      }catch(_){ }
    });
    if (sendBtn) sendBtn.addEventListener('click', sendTip);
  }

  document.addEventListener('DOMContentLoaded', hookGlobal);
  window.openTipModal = openTipModal;
})();
