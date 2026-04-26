'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  messages: [],
  systemPrompt: 'You are a helpful AI assistant. Be creative, thorough, and engaging.',
  isStreaming: false,
};

// ── Tab navigation ─────────────────────────────────────────────────────────
document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`tab-${tab}`).classList.add('active');
  });
});

// ── System Prompt ──────────────────────────────────────────────────────────
const systemPromptBtn = document.getElementById('system-prompt-btn');
const systemPromptPanel = document.getElementById('system-prompt-panel');
const systemPromptInput = document.getElementById('system-prompt-input');
const saveSystemPromptBtn = document.getElementById('save-system-prompt');
const cancelSystemPromptBtn = document.getElementById('cancel-system-prompt');

systemPromptBtn.addEventListener('click', () => {
  const open = systemPromptPanel.style.display !== 'none';
  systemPromptPanel.style.display = open ? 'none' : 'block';
  if (!open) systemPromptInput.focus();
});

saveSystemPromptBtn.addEventListener('click', () => {
  state.systemPrompt = systemPromptInput.value.trim() ||
    'You are a helpful AI assistant. Be creative, thorough, and engaging.';
  systemPromptPanel.style.display = 'none';
});

cancelSystemPromptBtn.addEventListener('click', () => {
  systemPromptInput.value = state.systemPrompt;
  systemPromptPanel.style.display = 'none';
});

// ── Clear chat ─────────────────────────────────────────────────────────────
document.getElementById('clear-chat-btn').addEventListener('click', () => {
  state.messages = [];
  const container = document.getElementById('chat-messages');
  container.innerHTML = `
    <div class="welcome-msg">
      <svg viewBox="0 0 24 24" fill="none" stroke="#7c3aed" stroke-width="1.5" width="48" height="48">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
      <h3>Start a conversation</h3>
      <p>Ask me anything — I'm here to help</p>
    </div>`;
});

// ── Chat input auto-resize ─────────────────────────────────────────────────
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');

chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + 'px';
  sendBtn.disabled = !chatInput.value.trim() || state.isStreaming;
});

chatInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (!sendBtn.disabled) sendMessage();
  }
});

sendBtn.addEventListener('click', sendMessage);

// ── Chat helpers ───────────────────────────────────────────────────────────
function addMessage(role, content, streaming = false) {
  const container = document.getElementById('chat-messages');

  // Remove welcome placeholder
  const welcome = container.querySelector('.welcome-msg');
  if (welcome) welcome.remove();

  const wrapper = document.createElement('div');
  wrapper.className = `message ${role}`;

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = role === 'user' ? 'U' : 'AI';

  const bubble = document.createElement('div');
  bubble.className = `msg-content${streaming ? ' streaming' : ''}`;
  bubble.textContent = content;

  wrapper.appendChild(avatar);
  wrapper.appendChild(bubble);
  container.appendChild(wrapper);
  container.scrollTop = container.scrollHeight;
  return bubble;
}

async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text || state.isStreaming) return;

  state.messages.push({ role: 'user', content: text });
  addMessage('user', text);

  chatInput.value = '';
  chatInput.style.height = 'auto';
  sendBtn.disabled = true;
  state.isStreaming = true;

  const bubble = addMessage('assistant', '', true);

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: state.messages, system: state.systemPrompt }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || 'Request failed');
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let assistantText = '';
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6);
        if (payload === '[DONE]') continue;
        try {
          const { text: chunk } = JSON.parse(payload);
          assistantText += chunk;
          bubble.textContent = assistantText;
          document.getElementById('chat-messages').scrollTop =
            document.getElementById('chat-messages').scrollHeight;
        } catch { /* skip malformed */ }
      }
    }

    bubble.classList.remove('streaming');
    state.messages.push({ role: 'assistant', content: assistantText });
  } catch (err) {
    bubble.classList.remove('streaming');
    bubble.style.color = '#fca5a5';
    bubble.textContent = `Error: ${err.message}`;
  } finally {
    state.isStreaming = false;
    sendBtn.disabled = !chatInput.value.trim();
    chatInput.focus();
  }
}

// ── Image generation ───────────────────────────────────────────────────────
const generateImageBtn = document.getElementById('generate-image-btn');
const imageResult = document.getElementById('image-result');

generateImageBtn.addEventListener('click', generateImage);

async function generateImage() {
  const prompt = document.getElementById('image-prompt').value.trim();
  if (!prompt) { alert('Please enter a prompt first.'); return; }

  const [w, h] = document.getElementById('image-dims').value.split('x').map(Number);
  const style = document.getElementById('image-style').value;

  generateImageBtn.disabled = true;
  imageResult.innerHTML = `
    <div class="loading-card">
      <div class="spinner"></div>
      <p>Generating your image…</p>
      <p style="font-size:0.75rem">This takes 5–15 seconds</p>
      <div class="progress-bar-wrap"><div class="progress-bar"></div></div>
    </div>`;

  try {
    const resp = await fetch('/api/generate-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, width: w, height: h, style }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || 'Generation failed');
    }

    const data = await resp.json();
    const imgData = data?.data?.[0];
    if (!imgData) throw new Error('No image data returned');

    const src = imgData.b64_json
      ? `data:image/png;base64,${imgData.b64_json}`
      : imgData.url;

    imageResult.innerHTML = `
      <div class="image-result-card">
        <img src="${src}" alt="${escapeHtml(prompt)}" />
        <div class="result-actions">
          <a href="${src}" download="generated.png" class="btn-primary btn-sm">Download</a>
          <span style="color:var(--text-muted);font-size:0.8rem;align-self:center">${w}×${h}</span>
        </div>
      </div>`;
  } catch (err) {
    imageResult.innerHTML = `<div class="error-card">Failed to generate image: ${escapeHtml(err.message)}</div>`;
  } finally {
    generateImageBtn.disabled = false;
  }
}

// ── Video generation ───────────────────────────────────────────────────────
const generateVideoBtn = document.getElementById('generate-video-btn');
const videoResult = document.getElementById('video-result');
let videoPollInterval = null;

generateVideoBtn.addEventListener('click', generateVideo);

async function generateVideo() {
  const prompt = document.getElementById('video-prompt').value.trim();
  if (!prompt) { alert('Please enter a prompt first.'); return; }

  const duration = document.getElementById('video-duration').value;

  generateVideoBtn.disabled = true;
  if (videoPollInterval) clearInterval(videoPollInterval);

  videoResult.innerHTML = `
    <div class="loading-card">
      <div class="spinner"></div>
      <p>Submitting video request…</p>
    </div>`;

  try {
    const resp = await fetch('/api/generate-video', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, duration }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || 'Submission failed');
    }

    const data = await resp.json();
    const jobId = data.job_id;
    if (!jobId) throw new Error('No job ID returned');

    videoResult.innerHTML = `
      <div class="loading-card" id="video-status-card">
        <div class="spinner"></div>
        <p id="video-status-text">Video queued — generating…</p>
        <p style="font-size:0.75rem">HuggingFace free tier: usually 2–5 minutes</p>
        <div class="progress-bar-wrap"><div class="progress-bar"></div></div>
      </div>`;

    pollVideoStatus(jobId);
  } catch (err) {
    videoResult.innerHTML = `<div class="error-card">Failed to start video generation: ${escapeHtml(err.message)}</div>`;
    generateVideoBtn.disabled = false;
  }
}

function pollVideoStatus(jobId) {
  let attempts = 0;
  const MAX_ATTEMPTS = 72; // 6 min max (72 × 5s)

  videoPollInterval = setInterval(async () => {
    attempts++;
    if (attempts > MAX_ATTEMPTS) {
      clearInterval(videoPollInterval);
      videoResult.innerHTML = `<div class="error-card">Video generation timed out. HuggingFace free tier can be busy — please try again.</div>`;
      generateVideoBtn.disabled = false;
      return;
    }

    try {
      const resp = await fetch(`/api/video-status?job_id=${encodeURIComponent(jobId)}`);
      const data = await resp.json();

      const statusEl = document.getElementById('video-status-text');
      if (statusEl) {
        if (data.status === 'pending') statusEl.textContent = 'Queued…';
        else if (data.status === 'processing') statusEl.textContent = 'Generating video…';
        else statusEl.textContent = `Status: ${data.status}`;
      }

      if (data.status === 'completed') {
        clearInterval(videoPollInterval);
        generateVideoBtn.disabled = false;
        const src = `data:video/mp4;base64,${data.video_b64}`;
        videoResult.innerHTML = `
          <div class="video-result-card">
            <video controls autoplay loop>
              <source src="${src}" type="video/mp4" />
            </video>
            <div class="result-actions">
              <a href="${src}" download="generated.mp4" class="btn-primary btn-sm">Download</a>
            </div>
          </div>`;
      } else if (data.status === 'error') {
        clearInterval(videoPollInterval);
        generateVideoBtn.disabled = false;
        videoResult.innerHTML = `<div class="error-card">${escapeHtml(data.error || 'Video generation failed.')}</div>`;
      }
    } catch {
      // silently continue polling on network hiccups
    }
  }, 5000);
}

// ── Utility ────────────────────────────────────────────────────────────────
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
