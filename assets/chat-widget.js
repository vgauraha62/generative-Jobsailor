(function() {
  // Inject Royal Chatbot Floating Widget
  if (document.getElementById('royal-chat-widget-root')) return;

  const style = document.createElement('style');
  style.textContent = `
    #royal-chat-widget-root {
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 9999;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .royal-widget-btn {
      background: linear-gradient(135deg, #a855f7 0%, #4fd1a5 100%);
      border: none;
      color: #0b0f14;
      font-weight: 700;
      font-size: 0.9rem;
      padding: 12px 20px;
      border-radius: 999px;
      box-shadow: 0 4px 20px rgba(168, 85, 247, 0.4);
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: all 0.25s ease;
    }
    .royal-widget-btn:hover {
      transform: translateY(-2px) scale(1.03);
      box-shadow: 0 6px 25px rgba(168, 85, 247, 0.6);
    }
    .royal-chat-drawer {
      display: none;
      position: fixed;
      bottom: 84px;
      right: 24px;
      width: 400px;
      max-width: calc(100vw - 32px);
      height: 540px;
      max-height: calc(100vh - 110px);
      background: #131a22;
      border: 1px solid rgba(168, 85, 247, 0.35);
      border-radius: 14px;
      box-shadow: 0 12px 40px rgba(0, 0, 0, 0.6), 0 0 20px rgba(168, 85, 247, 0.2);
      flex-direction: column;
      overflow: hidden;
      z-index: 9999;
      animation: drawerSlideUp 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    }
    @keyframes drawerSlideUp {
      from { opacity: 0; transform: translateY(16px) scale(0.96); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
    .royal-drawer-header {
      background: linear-gradient(135deg, rgba(168, 85, 247, 0.15) 0%, rgba(79, 209, 165, 0.05) 100%);
      padding: 14px 16px;
      border-bottom: 1px solid rgba(168, 85, 247, 0.2);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .royal-drawer-title {
      display: flex;
      align-items: center;
      gap: 8px;
      color: #e4e9ee;
      font-size: 0.92rem;
      font-weight: 600;
    }
    .royal-drawer-title .dot {
      width: 7px; height: 7px; border-radius: 50%;
      background: #a855f7; box-shadow: 0 0 8px #a855f7;
    }
    .royal-drawer-close {
      background: none; border: none; color: #8a98aa;
      font-size: 1.2rem; cursor: pointer; padding: 2px 6px; border-radius: 4px;
    }
    .royal-drawer-close:hover { color: #fff; background: rgba(255,255,255,0.05); }
    .royal-drawer-body {
      flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 12px;
    }
    .royal-bubble {
      padding: 10px 14px; border-radius: 10px; font-size: 0.88rem; line-height: 1.5; word-break: break-word; max-width: 90%;
    }
    .royal-bubble.user {
      align-self: flex-end; background: #0e131a; border: 1px solid #232d38; color: #e4e9ee; border-top-right-radius: 2px;
    }
    .royal-bubble.assistant {
      align-self: flex-start; background: rgba(168, 85, 247, 0.08); border: 1px solid rgba(168, 85, 247, 0.3); color: #e4e9ee; border-top-left-radius: 2px;
    }
    .royal-drawer-footer {
      padding: 10px 14px; background: #0e131a; border-top: 1px solid #232d38; display: flex; gap: 8px; align-items: center;
    }
    .royal-drawer-input {
      flex: 1; background: #131a22; border: 1px solid #232d38; border-radius: 8px; color: #e4e9ee; padding: 8px 12px; font-size: 0.88rem; outline: none;
    }
    .royal-drawer-input:focus { border-color: #a855f7; box-shadow: 0 0 10px rgba(168, 85, 247, 0.3); }
    .royal-drawer-send {
      background: linear-gradient(135deg, #a855f7 0%, #4fd1a5 100%); border: none; border-radius: 8px; padding: 8px 14px; font-weight: bold; cursor: pointer; color: #0b0f14;
    }
    .royal-drawer-send:disabled { opacity: 0.5; cursor: not-allowed; }
  `;
  document.head.appendChild(style);

  const container = document.createElement('div');
  container.id = 'royal-chat-widget-root';
  container.innerHTML = `
    <button class="royal-widget-btn" id="royal-widget-toggle" aria-label="Open AI Assistant">
      <span>👑</span>
      <span>Ask AI</span>
    </button>
    <div class="royal-chat-drawer" id="royal-chat-drawer">
      <div class="royal-drawer-header">
        <div class="royal-drawer-title">
          <span class="dot"></span>
          <span>Royal RAG Assistant</span>
        </div>
        <div style="display:flex;align-items:center;gap:6px">
          <a href="chat.html" style="font-size:0.75rem;color:#a855f7;text-decoration:none;margin-right:6px">Expand ↗</a>
          <button class="royal-drawer-close" id="royal-drawer-close">✕</button>
        </div>
      </div>
      <div class="royal-drawer-body" id="royal-drawer-body">
        <div class="royal-bubble assistant">
          👑 <strong>Royal Assistant Ready.</strong><br>Ask any question about your resume, applications, or job match!
        </div>
      </div>
      <div class="royal-drawer-footer">
        <input type="text" class="royal-drawer-input" id="royal-drawer-input" placeholder="Type your question..." />
        <button class="royal-drawer-send" id="royal-drawer-send">Send</button>
      </div>
    </div>
  `;
  document.body.appendChild(container);

  fetch('/api/status',{credentials:'same-origin'}).then(r=>r.json()).then(s=>{
    const btn=document.getElementById('royal-widget-toggle');
    if(!btn) return;
    const g=(s.budgets||{}).gemini||s.budget||{};
    if(g.daily_limit) btn.innerHTML=`<span>👑</span><span>Ask AI</span><span style="font-size:0.7rem;background:rgba(0,0,0,0.2);padding:2px 6px;border-radius:999px;margin-left:4px">💰 ${g.calls_used}/${g.daily_limit}</span>`;
  }).catch(()=>{});
  const toggleBtn = document.getElementById('royal-widget-toggle');
  const drawer = document.getElementById('royal-chat-drawer');
  const closeBtn = document.getElementById('royal-drawer-close');
  const input = document.getElementById('royal-drawer-input');
  const sendBtn = document.getElementById('royal-drawer-send');
  const body = document.getElementById('royal-drawer-body');

  toggleBtn.addEventListener('click', () => {
    const isShown = drawer.style.display === 'flex';
    drawer.style.display = isShown ? 'none' : 'flex';
    if (!isShown) input.focus();
  });

  closeBtn.addEventListener('click', () => {
    drawer.style.display = 'none';
  });

  async function handleSend() {
    const text = input.value.trim();
    if (!text) return;

    const userBubble = document.createElement('div');
    userBubble.className = 'royal-bubble user';
    userBubble.textContent = text;
    body.appendChild(userBubble);
    input.value = '';
    body.scrollTop = body.scrollHeight;

    const loadingBubble = document.createElement('div');
    loadingBubble.className = 'royal-bubble assistant';
    loadingBubble.textContent = 'Thinking...';
    body.appendChild(loadingBubble);
    body.scrollTop = body.scrollHeight;

    sendBtn.disabled = true;

    try {
      const res = await fetch('/api/rag/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: text }),
        credentials: 'same-origin'
      });
      const ct = res.headers.get('content-type') || '';
      let data;
      if (ct.includes('application/json')) {
        data = await res.json();
      } else {
        const txt = await res.text();
        throw new Error(txt.slice(0,300) || `HTTP ${res.status}`);
      }
      if (!res.ok) {
        const msg = data.detail || data.answer || `HTTP ${res.status}`;
        loadingBubble.textContent = '⚠️ ' + msg;
        return;
      }
      loadingBubble.innerHTML = `<strong>${escape(data.answer || 'NEEDS_REVIEW')}</strong><div style="font-size:0.72rem;color:#8a98aa;margin-top:4px">${data.verified ? '✓ Grounded' : '⚠ Review Needed'}</div>`;
    } catch (e) {
      loadingBubble.textContent = 'Error: ' + e.message;
    } finally {
      sendBtn.disabled = false;
      body.scrollTop = body.scrollHeight;
    }
  }

  sendBtn.addEventListener('click', handleSend);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSend();
    }
  });

  function escape(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
})();
