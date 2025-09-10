document.addEventListener("DOMContentLoaded", function () {
  const postForm = document.getElementById("postForm");
  const appId = (typeof window !== 'undefined' && window.HIVE_APP_ID) ? window.HIVE_APP_ID : 'hive.micro';
  const MAX_LEN = (typeof window !== 'undefined' && window.HIVE_MAX_CONTENT_LEN) ? Number(window.HIVE_MAX_CONTENT_LEN) : 512;
  const ta = document.getElementById("postContent");
  const counterEl = document.getElementById('charCounter');
  const params = new URLSearchParams(window.location.search);
  const replyTo = params.get('reply_to');
  const replyAuthor = params.get('author');
  const notice = document.getElementById('replyNotice');
  const preview = document.getElementById('replyPreview');
  const addImageBtn = document.getElementById('addImageBtn');
  const imageModalEl = document.getElementById('imageUploadModal');
  const imageFileInput = document.getElementById('imageFileInput');
  const imageUploadBtn = document.getElementById('imageUploadBtn');
  const imageUploadStatus = document.getElementById('imageUploadStatus');

  function escapeHTML(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
  // --- Image Upload Helpers (images.hive.blog via Keychain) ---
  function setImageStatus(msg, type){
    if (!imageUploadStatus) return;
    imageUploadStatus.textContent = msg || '';
    imageUploadStatus.className = 'small ' + (type === 'error' ? 'text-danger' : type === 'success' ? 'text-success' : 'text-muted');
  }

  function insertAtCursor(textarea, text){
    try {
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const before = textarea.value.substring(0, start);
      const after = textarea.value.substring(end);
      textarea.value = before + text + after;
      const pos = start + text.length;
      textarea.selectionStart = textarea.selectionEnd = pos;
      textarea.focus();
      updateCounter();
    } catch (_) { /* ignore */ }
  }

  async function uploadImageToImagesHiveBlog(file){
    return new Promise((resolve, reject) => {
      try {
        const username = localStorage.getItem('hive.username');
        if (!username) { reject(new Error('Please login first.')); return; }
        if (!window.hive_keychain) { reject(new Error('Hive Keychain not detected.')); return; }
        const reader = new FileReader();
        reader.onload = (event) => {
          try {
            const imageData = new Uint8Array(event.target.result);
            const enc = new TextEncoder();
            const challengeBytes = enc.encode('ImageSigningChallenge');
            const messageBytes = new Uint8Array(challengeBytes.length + imageData.length);
            messageBytes.set(challengeBytes, 0);
            messageBytes.set(imageData, challengeBytes.length);
            const bufferObj = { type: 'Buffer', data: Array.from(messageBytes) };
            window.hive_keychain.requestSignBuffer(username, JSON.stringify(bufferObj), 'Posting', (response) => {
              if (!response || !response.success) { reject(new Error(response && response.message ? response.message : 'Signature failed')); return; }
              const signature = response.result;
              const formData = new FormData();
              formData.append('file', file);
              fetch(`https://images.hive.blog/${encodeURIComponent(username)}/${encodeURIComponent(signature)}`, { method: 'POST', body: formData })
                .then((res) => res.json())
                .then((data) => {
                  if (data && data.url) resolve(data.url); else reject(new Error('No URL in response'));
                })
                .catch((err) => reject(err));
            });
          } catch (e) { reject(e); }
        };
        reader.onerror = () => reject(new Error('Failed to read file'));
        reader.readAsArrayBuffer(file);
      } catch (e) { reject(e); }
    });
  }

  function openImageModal(){
    try {
      if (!imageModalEl) return;
      if (imageFileInput) imageFileInput.value = '';
      setImageStatus('', '');
      const modal = new bootstrap.Modal(imageModalEl);
      modal.show();
      imageModalEl.__modalInstance = modal;
    } catch (_) {}
  }

  async function handleImageUpload(){
    try {
      if (!imageFileInput || !imageFileInput.files || imageFileInput.files.length === 0) {
        setImageStatus('Please select an image file.', 'error');
        return;
      }
      const file = imageFileInput.files[0];
      setImageStatus('Signing and uploading…', '');
      const url = await uploadImageToImagesHiveBlog(file);
      setImageStatus('Uploaded successfully', 'success');
      // Insert markdown at cursor
      const md = `\n![](${url})\n`;
      if (ta) insertAtCursor(ta, md);
      if (imageModalEl && imageModalEl.__modalInstance) imageModalEl.__modalInstance.hide();
      if (window.showToast) showToast('Image uploaded', 'success');
    } catch (e) {
      setImageStatus('Upload failed: ' + (e && e.message ? e.message : e), 'error');
      if (window.showToast) showToast('Image upload failed: ' + (e && e.message ? e.message : e), 'danger');
    }
  }

  if (addImageBtn) addImageBtn.addEventListener('click', openImageModal);
  if (imageUploadBtn) imageUploadBtn.addEventListener('click', handleImageUpload);

  // Drag & Drop support on the textarea
  if (ta) {
    ta.addEventListener('dragover', (e) => { e.preventDefault(); });
    ta.addEventListener('dragenter', (e) => { e.preventDefault(); });
    ta.addEventListener('drop', async (e) => {
      try {
        e.preventDefault();
        const files = e.dataTransfer && e.dataTransfer.files ? e.dataTransfer.files : null;
        if (!files || files.length === 0) return;
        const file = Array.from(files).find(f => /^image\//.test(f.type));
        if (!file) return;
        if (window.showToast) showToast('Uploading image…', 'info');
        const url = await uploadImageToImagesHiveBlog(file);
        const md = `\n![](${url})\n`;
        insertAtCursor(ta, md);
        if (window.showToast) showToast('Image uploaded', 'success');
      } catch (err) {
        if (window.showToast) showToast('Image upload failed: ' + (err && err.message ? err.message : err), 'danger');
      }
    });
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
  // Override with shared helpers if available
  try {
    if (window.escapeHTML) {
      escapeHTML = function (s) { return window.escapeHTML(s); };
    }
    if (window.linkifyText) {
      linkify = function (t) { return window.linkifyText(t); };
    }
  } catch (e) {}
  if (replyTo && notice) {
    const who = replyAuthor ? ` @${replyAuthor}` : '';
    notice.classList.remove('d-none');
    notice.innerHTML = `Replying to<strong>${who}</strong>`;
  }
  // Load compact parent preview
  if (replyTo && preview) {
    (async () => {
      try {
        const res = await fetch(`/api/v1/post/${encodeURIComponent(replyTo)}`);
        if (!res.ok) throw new Error("load failed");
        const data = await res.json();
        const item = data && data.item ? data.item : null;
        if (!item) return;
        const author = escapeHTML(item.author);
        const authorSlug = encodeURIComponent(String(item.author).toLowerCase());
        const dtStr = new Date(item.timestamp).toLocaleString();
        const trxHtml = item.trx_id ? (' · trx: ' + (window.buildTrxLink ? window.buildTrxLink(item.trx_id) : '')) : '';
        const card = document.createElement('div');
        card.className = 'card border-secondary';
        const body = document.createElement('div');
        body.className = 'card-body py-2';
        const header = document.createElement('div');
        header.className = 'd-flex align-items-center gap-2 mb-1';
        const avatar = (window.createAvatarImg ? window.createAvatarImg(item.author, 24) : (function(){ const im=document.createElement('img'); im.src=`https://images.hive.blog/u/${authorSlug}/avatar`; im.alt=`@${author}`; im.width=24; im.height=24; im.loading='lazy'; im.className='rounded-circle flex-shrink-0'; im.style.objectFit='cover'; return im; })());
        const strong = document.createElement('strong');
        strong.className = 'mb-0';
        strong.style.fontSize = '0.95rem';
        strong.innerHTML = `<a href="/u/${authorSlug}">@${author}</a>`;
        header.appendChild(avatar);
        header.appendChild(strong);
        const meta = document.createElement('div');
        meta.className = 'small text-muted';
        meta.innerHTML = `${dtStr}${trxHtml}`;
        const contentDiv = document.createElement('div');
        contentDiv.className = 'card-text mt-1';
        contentDiv.innerHTML = item.html || linkify(item.content);
        body.appendChild(header);
        body.appendChild(meta);
        body.appendChild(contentDiv);
        card.appendChild(body);
        preview.innerHTML = '';
        preview.appendChild(card);
        preview.classList.remove('d-none');
      } catch (e) {
        // leave preview hidden on failure
      }
    })();
  }
  // Prefill with @author and focus caret
  if (replyAuthor) {
    const ta = document.getElementById("postContent");
    if (ta && !ta.value) {
      ta.value = `@${replyAuthor} `;
      ta.focus();
      // Move caret to end
      ta.selectionStart = ta.selectionEnd = ta.value.length;
    }
  }

  function updateCounter() {
    if (!ta || !counterEl) return;
    const len = (ta.value || '').length;
    counterEl.textContent = `${len} / ${MAX_LEN}`;
    if (len > MAX_LEN) {
      counterEl.classList.add('text-danger');
    } else {
      counterEl.classList.remove('text-danger');
    }
  }
  if (ta) {
    ta.addEventListener('input', updateCounter);
    updateCounter();
  }

  postForm.addEventListener("submit", function (e) {
    e.preventDefault();

    const content = ta.value;
    const username = localStorage.getItem("hive.username");

    if (!username) {
      if (window.showToast) showToast("Please login first", 'warning');
      return;
    }
    if ((content || '').length > MAX_LEN) {
      if (window.showToast) showToast(`Post is too long. Maximum ${MAX_LEN} characters.`, 'danger');
      return;
    }
    // Extract mentions and tags client-side
    function extractMentionsTags(text) {
      const mentions = new Set();
      const tags = new Set();
      // @mentions: hive usernames are lowercase letters, digits, and dashes
      const mRe = /(^|\s)@([a-z0-9\-\.]+)/gi;
      let m;
      while ((m = mRe.exec(text))) {
        const u = (m[2] || "").toLowerCase();
        if (u) mentions.add(u);
      }
      // #tags: lowercase letters, digits, dashes
      const tRe = /(^|\s)#([a-z0-9\-]+)/gi;
      let t;
      while ((t = tRe.exec(text))) {
        const tag = (t[2] || "").toLowerCase();
        if (tag) tags.add(tag);
      }
      return { mentions: Array.from(mentions), tags: Array.from(tags) };
    }

    const { mentions, tags } = extractMentionsTags(content || "");

    const payload = {
      app: appId,
      v: 1,
      type: "post",
      content: content,
      mentions: mentions,
      reply_to: replyTo,
      tags: tags,
    };

    if (!window.hive_keychain) {
      if (window.showToast) showToast("Hive Keychain not detected", 'warning');
      return;
    }

    const operations = [
      [
        "custom_json",
        {
          required_auths: [],
          required_posting_auths: [username],
          id: appId,
          json: JSON.stringify(payload),
        },
      ],
    ];

    window.hive_keychain.requestBroadcast(
      username,
      operations,
      "Posting",
      function (response) {
        console.log("Keychain broadcast response", response);
        if (response && response.success) {
          // Redirect to feed without popup; allow brief time for watcher ingestion
          setTimeout(() => (window.location.href = "/feed"), 300);
        } else {
          const msg = response && response.message ? response.message : "Unknown error";
          if (window.showToast) showToast("Error posting to Hive: " + msg, 'danger');
        }
      }
    );
  });
});
