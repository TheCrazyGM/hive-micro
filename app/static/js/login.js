function getCurrentUTCDateTime() {
  const now = new Date();
  return now.toISOString();
}
document
  .getElementById("loginForm")
  .addEventListener("submit", function (e) {
    e.preventDefault();
    const username = document.getElementById("username").value.trim();
    const datetimeToSign = getCurrentUTCDateTime();
    window.hive_keychain.requestSignBuffer(
      username,
      datetimeToSign,
      "Posting",
      function (response) {
        if (response.success) {
          const proof = response.result;
          const pubkey =
            response.publicKey ||
          (response.data && response.data.publicKey) ||
          null;
          const payload = {
            challenge: proof,
            username: username,
            pubkey: pubkey,
            proof: datetimeToSign,
          };
          fetch("/api/v1/login", {
            method: "POST",
            headers: { "Content-Type": "application/json", 'X-CSRF-Token': (document.querySelector('meta[name="csrf-token"]')?.content || window.CSRF_TOKEN || '') },
            body: JSON.stringify(payload),
            credentials: "same-origin",
          })
            .then(async (r) => {
              const data = await r.json().catch(() => ({}));
              if (r.ok && data.success) {
                localStorage.setItem("hive.username", username);
                if (window.showToast) showToast('Logged in successfully', 'success');
                window.location.href = "/feed";
              } else {
                const msg = data && (data.error || JSON.stringify(data));
                if (window.showToast) showToast("Login failed: " + (msg || r.status + " " + r.statusText), 'danger');
              }
            })
            .catch((e) => {
              if (window.showToast) showToast("Network error: " + e.message, 'danger');
            });
        }
      },
    );
  });
