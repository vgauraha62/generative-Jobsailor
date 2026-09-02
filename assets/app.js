// Shared helpers for every page.

async function apiGet(path) {
  const res = await fetch(path, { credentials: "same-origin" });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("unauthenticated");
  }
  if (!res.ok) {
    throw new Error(`${path} -> HTTP ${res.status}`);
  }
  return res.json();
}

function fmtNumber(n) { return Number(n).toLocaleString(); }
function fmtTimestamp(unixSeconds) {
  const d = new Date(unixSeconds * 1000);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function statusBadge(status) {
  const known = ["applied", "failed", "review", "skipped", "unprocessed"];
  const cls = known.includes(status) ? status : "skipped";
  return `<span class="badge ${cls}" aria-label="status ${status}"><span class="dot" style="display:inline-block;width:6px;height:6px;border-radius:50%;background:currentColor;margin-right:4px"></span>${status}</span>`;
}
function kindBadge(kind) { return `<span class="badge ${kind}" aria-label="kind ${kind}">${kind}</span>`; }
function rawJson(obj) { return `<pre class="raw-json">${escapeHtml(JSON.stringify(obj, null, 2))}</pre>`; }
function escapeHtml(str) { return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function el(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstChild; }

function setProcessing(btn, processing) {
  if (processing) { btn.dataset.orig = btn.innerHTML; btn.disabled = true; btn.innerHTML = `Processing... <span class="spinner" aria-hidden="true"></span>`; }
  else { btn.disabled = false; btn.innerHTML = btn.dataset.orig || btn.textContent; }
}

function showToast(msg, retryFn) {
  let root = document.getElementById("toast-root");
  if (!root) { root = document.createElement("div"); root.id = "toast-root"; root.setAttribute("aria-live", "assertive"); document.body.appendChild(root); }
  const t = document.createElement("div");
  t.className = "toast"; t.setAttribute("role", "alert");
  t.innerHTML = `<span class="msg">${escapeHtml(msg)}</span>`;
  if (retryFn) { const b = document.createElement("button"); b.className = "btn retry"; b.textContent = "Retry"; b.setAttribute("aria-label", "Retry"); b.onclick = () => { t.remove(); retryFn(); }; t.appendChild(b); }
  const close = document.createElement("button"); close.textContent = "×"; close.className = "btn"; close.style.minWidth = "32px"; close.onclick = () => t.remove(); t.appendChild(close);
  root.appendChild(t);
  setTimeout(() => t.remove(), 6000);
}

function triggerConfetti() {
  const c = document.createElement("canvas");
  c.style.position = "fixed"; c.style.inset = "0"; c.style.pointerEvents = "none"; c.style.zIndex = "50";
  c.width = window.innerWidth; c.height = window.innerHeight;
  document.body.appendChild(c);
  const ctx = c.getContext("2d");
  const parts = Array.from({length: 60}, () => ({x: c.width/2, y: c.height/3, vx: (Math.random()-0.5)*12, vy: -Math.random()*8 -2, color: ["#4fd1a5","#ffb454","#8fb4ff"][Math.floor(Math.random()*3)]}));
  let start = performance.now();
  function frame(now) {
    const elapsed = now - start;
    if (elapsed > 1400) { c.remove(); return; }
    ctx.clearRect(0,0,c.width,c.height);
    parts.forEach(p => { p.x+=p.vx; p.y+=p.vy; p.vy+=0.35; ctx.fillStyle=p.color; ctx.fillRect(p.x,p.y,4,6); });
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}
