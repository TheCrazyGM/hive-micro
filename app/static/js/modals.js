// Bootstrap-based modal helpers
(function () {
  function showReasonModal(options) {
    options = options || {};
    var required = !!options.required;
    var title = options.title || 'Provide a reason';
    var placeholder = options.placeholder || 'Enter reason...';
    var help = options.help || (required ? 'A reason is required.' : 'Optional');
    var el = document.getElementById('reasonModal');
    if (!el) return Promise.resolve(null);
    var ttl = el.querySelector('#reasonModalLabel');
    var ta = el.querySelector('#reasonInput');
    var helpEl = el.querySelector('#reasonHelp');
    var okBtn = el.querySelector('#reasonOkBtn');
    var cancelBtn = el.querySelector('#reasonCancelBtn');
    ttl.textContent = title;
    ta.value = '';
    ta.placeholder = placeholder;
    helpEl.textContent = help;
    return new Promise(function (resolve) {
      var modal = bootstrap.Modal.getOrCreateInstance(el, { backdrop: 'static' });
      function cleanup() {
        okBtn.removeEventListener('click', onOk);
        cancelBtn.removeEventListener('click', onCancel);
        el.removeEventListener('hidden.bs.modal', onHidden);
      }
      function onOk() {
        var val = (ta.value || '').trim();
        if (required && !val) {
          if (window.showToast) showToast('Reason is required', 'warning');
          ta.focus();
          return;
        }
        cleanup();
        modal.hide();
        resolve(val);
      }
      function onCancel() { cleanup(); resolve(null); }
      function onHidden() { cleanup(); resolve(null); }
      okBtn.addEventListener('click', onOk);
      cancelBtn.addEventListener('click', onCancel);
      el.addEventListener('hidden.bs.modal', onHidden);
      modal.show();
      setTimeout(function () { ta.focus(); }, 150);
    });
  }
  window.showReasonModal = showReasonModal;

  function showInfoModal(options) {
    options = options || {};
    var title = options.title || 'Info';
    var text = options.text || '';
    var el = document.getElementById('reasonModal');
    if (!el) return Promise.resolve();
    var ttl = el.querySelector('#reasonModalLabel');
    var ta = el.querySelector('#reasonInput');
    var helpEl = el.querySelector('#reasonHelp');
    var okBtn = el.querySelector('#reasonOkBtn');
    var cancelBtn = el.querySelector('#reasonCancelBtn');
    // Save defaults
    var prevOkText = okBtn.textContent;
    var prevRO = ta.readOnly;
    var prevHelp = helpEl.textContent;
    ttl.textContent = title;
    ta.value = text;
    ta.readOnly = true;
    helpEl.textContent = '';
    okBtn.textContent = 'Close';
    cancelBtn.classList.add('d-none');
    return new Promise(function (resolve) {
      var modal = bootstrap.Modal.getOrCreateInstance(el, { backdrop: 'static' });
      function cleanup() {
        okBtn.removeEventListener('click', onClose);
        el.removeEventListener('hidden.bs.modal', onHidden);
        // restore defaults
        okBtn.textContent = prevOkText;
        ta.readOnly = prevRO;
        helpEl.textContent = prevHelp;
        cancelBtn.classList.remove('d-none');
      }
      function onClose() { modal.hide(); }
      function onHidden() { cleanup(); resolve(); }
      okBtn.addEventListener('click', onClose);
      el.addEventListener('hidden.bs.modal', onHidden);
      modal.show();
    });
  }
  window.showInfoModal = showInfoModal;
})();
