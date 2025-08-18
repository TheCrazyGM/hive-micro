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
          fetch("/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
            credentials: "same-origin",
          })
            .then(async (r) => {
              const data = await r.json().catch(() => ({}));
              if (r.ok && data.success) {
                localStorage.setItem("hive_username", username);
                window.location.href = "/feed";
              } else {
                const msg = data && (data.error || JSON.stringify(data));
                alert("Login failed: " + (msg || r.status + " " + r.statusText));
              }
            })
            .catch((e) => {
              alert("Network error: " + e.message);
            });
        }
      },
    );
  });
