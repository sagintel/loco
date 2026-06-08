// === Global State ===
let currentConfig = {};
let systemStatsInterval = null;
let chatHistory = [];

// === DOM Elements ===
const ollamaStatusEl = document.getElementById('ollama-status');
const cpuBar = document.getElementById('cpu-bar');
const cpuText = document.getElementById('cpu-text');
const ramBar = document.getElementById('ram-bar');
const ramText = document.getElementById('ram-text');
const footerWorkspace = document.getElementById('footer-workspace');

const configForm = document.getElementById('config-form');
const gatewayModeSelect = document.getElementById('gateway-mode');
const runnerTypeSelect = document.getElementById('runner-type');
const enableCascadeCheck = document.getElementById('enable-cascade');
const enableRAGCheck = document.getElementById('enable-rag');
const reasoningModelSelect = document.getElementById('reasoning-model');
const codingModelSelect = document.getElementById('coding-model');
const ollamaUrlInput = document.getElementById('ollama-url');
const ollamaUrlContainer = document.getElementById('ollama-url-container');

const nativeRunnerCard = document.getElementById('native-runner-card');
const ollamaRunnerCard = document.getElementById('ollama-runner-card');
const nativeInstallStatus = document.getElementById('native-install-status');
const btnInstallNative = document.getElementById('btn-install-native');
const nativeDownloadModelSelect = document.getElementById('native-download-model-select');
const btnDownloadNativeModel = document.getElementById('btn-download-native-model');
const nativeLocalModels = document.getElementById('native-local-models');
const btnStartNativeServer = document.getElementById('btn-start-native-server');
const btnStopNativeServer = document.getElementById('btn-stop-native-server');
const nativeProgressContainer = document.getElementById('native-progress-container');
const nativeStatusText = document.getElementById('native-status-text');
const nativePercentText = document.getElementById('native-percent-text');
const nativeProgressBar = document.getElementById('native-progress-bar');

const pullModelNameInput = document.getElementById('pull-model-name');
const btnPullModel = document.getElementById('btn-pull-model');
const pullProgressContainer = document.getElementById('pull-progress-container');
const pullStatusText = document.getElementById('pull-status-text');
const pullPercentText = document.getElementById('pull-percent-text');
const pullProgressBar = document.getElementById('pull-progress-bar');

const skillsListEl = document.getElementById('skills-list');
const btnToggleSkillForm = document.getElementById('btn-toggle-skill-form');
const skillCreateForm = document.getElementById('skill-create-form');
const btnCancelSkill = document.getElementById('btn-cancel-skill');

const chatMessagesEl = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const btnSendChat = document.getElementById('btn-send-chat');
const btnClearChat = document.getElementById('btn-clear-chat');
const activeRAGIndicator = document.getElementById('active-rag-indicator');
const speedIndicator = document.getElementById('speed-indicator');

const btnIndexNow = document.getElementById('btn-index-now');
const btnClearIndex = document.getElementById('btn-clear-index');
const ragStatFiles = document.getElementById('rag-stat-files');
const ragStatChunks = document.getElementById('rag-stat-chunks');
const ragStatSize = document.getElementById('rag-stat-size');
const ragSearchQuery = document.getElementById('rag-search-query');
const btnRAGSearch = document.getElementById('btn-rag-search');
const ragSearchResults = document.getElementById('rag-search-results');
const consoleLogs = document.getElementById('console-logs');

// === Helpers ===
function writeLog(msg) {
    const ts = new Date().toLocaleTimeString();
    consoleLogs.textContent += `\n[${ts}] ${msg}`;
    consoleLogs.scrollTop = consoleLogs.scrollHeight;
}
function formatBytes(b) {
    if (b === 0) return '0 B';
    const k = 1024, s = ['B','KB','MB','GB'];
    const i = Math.floor(Math.log(b) / Math.log(k));
    return parseFloat((b / Math.pow(k, i)).toFixed(2)) + ' ' + s[i];
}
function escapeHTML(str) {
    return str.replace(/[&<>'"]/g, t => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[t]||t));
}

// === API Fetchers ===
async function fetchStatus() {
    try {
        const r = await fetch('/api/status');
        if (!r.ok) throw new Error('Status fetch failed');
        const d = await r.json();
        if (d.ollama_status === 'online') {
            ollamaStatusEl.className = 'status-pill online';
            ollamaStatusEl.querySelector('.status-text').textContent = 'Engine Online';
        } else {
            ollamaStatusEl.className = 'status-pill offline';
            ollamaStatusEl.querySelector('.status-text').textContent = 'Engine Offline';
        }
        cpuBar.style.width = d.cpu_usage_percent + '%';
        cpuText.textContent = d.cpu_usage_percent + '%';
        ramBar.style.width = d.ram_usage_percent + '%';
        ramText.textContent = `${d.ram_usage_percent}% (${d.ram_free_gb} GB free / ${d.ram_total_gb} GB)`;
        ragStatFiles.textContent = d.rag_stats.total_files;
        ragStatChunks.textContent = d.rag_stats.total_chunks;
        ragStatSize.textContent = formatBytes(d.rag_stats.db_size_bytes);
        footerWorkspace.textContent = d.workspace_dir;
    } catch (e) {
        ollamaStatusEl.className = 'status-pill offline';
        ollamaStatusEl.querySelector('.status-text').textContent = 'Gateway Offline';
    }
}

async function fetchConfig() {
    try {
        const r = await fetch('/api/config');
        if (!r.ok) throw new Error('Config fetch fail');
        currentConfig = await r.json();
        enableCascadeCheck.checked = currentConfig.enable_cascade;
        enableRAGCheck.checked = currentConfig.enable_rag;
        reasoningModelSelect.value = currentConfig.reasoning_model;
        codingModelSelect.value = currentConfig.coding_model;
        ollamaUrlInput.value = currentConfig.ollama_url;
        gatewayModeSelect.value = currentConfig.gateway_mode || 'code';
        runnerTypeSelect.value = currentConfig.runner_type || 'ollama';
        toggleRunnerUI();
        updateRAGIndicator();
    } catch (e) { writeLog('Config load error: ' + e.message); }
}

async function fetchSkills() {
    try {
        const r = await fetch('/api/skills');
        if (!r.ok) throw new Error('Skills fetch fail');
        const d = await r.json();
        skillsListEl.innerHTML = '';
        if (d.skills.length === 0) {
            skillsListEl.innerHTML = '<div class="skill-item">No skills found.</div>';
            return;
        }
        d.skills.forEach(s => {
            let icon = 'fa-lightbulb';
            if (s.id.includes('test')) icon = 'fa-vial';
            else if (s.id.includes('review')) icon = 'fa-file-shield';
            else if (s.id.includes('optimize')) icon = 'fa-gauge-high';
            const el = document.createElement('div');
            el.className = 'skill-item';
            el.innerHTML = `<div class="skill-icon"><i class="fa-solid ${icon}"></i></div><div class="skill-details"><h4>${s.title}</h4><p>${s.description}</p></div>`;
            skillsListEl.appendChild(el);
        });
    } catch (e) { skillsListEl.innerHTML = '<div class="skill-item">Failed to load skills.</div>'; }
}

async function fetchNativeStatus() {
    try {
        const r = await fetch('/api/runner/status');
        if (!r.ok) return;
        const d = await r.json();
        nativeInstallStatus.textContent = d.is_installed ? 'Installed' : 'Not Installed';
        nativeInstallStatus.className = 'badge ' + (d.is_installed ? 'badge-success' : 'badge-danger');
        nativeLocalModels.innerHTML = '';
        if (d.downloaded_models.length === 0) {
            nativeLocalModels.innerHTML = '<option value="">No local GGUFs found</option>';
        } else {
            d.downloaded_models.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.name;
                opt.textContent = `${m.name} (${formatBytes(m.size_bytes)})`;
                nativeLocalModels.appendChild(opt);
            });
        }
    } catch (e) { /* ignore */ }
}

function updateRAGIndicator() {
    activeRAGIndicator.classList.toggle('hidden', !enableRAGCheck.checked);
}

function toggleRunnerUI() {
    const isNative = runnerTypeSelect.value === 'native';
    nativeRunnerCard.classList.toggle('hidden', !isNative);
    ollamaRunnerCard.classList.toggle('hidden', isNative);
    ollamaUrlContainer.style.display = isNative ? 'none' : 'block';
    if (isNative) fetchNativeStatus();
}

// === Event Listeners ===

runnerTypeSelect.addEventListener('change', toggleRunnerUI);

// Config save
configForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
        enable_cascade: enableCascadeCheck.checked,
        enable_rag: enableRAGCheck.checked,
        reasoning_model: reasoningModelSelect.value,
        coding_model: codingModelSelect.value,
        ollama_url: ollamaUrlInput.value,
        gateway_mode: gatewayModeSelect.value,
        runner_type: runnerTypeSelect.value
    };
    try {
        const r = await fetch('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
        if (!r.ok) throw new Error('Save failed');
        const d = await r.json();
        currentConfig = d.config;
        writeLog('Configuration saved successfully.');
        updateRAGIndicator();
    } catch (e) { writeLog('Error saving: ' + e.message); }
});

// --- Ollama Model Pull ---
btnPullModel.addEventListener('click', async () => {
    const name = pullModelNameInput.value.trim();
    if (!name) return alert('Please specify a model name.');
    btnPullModel.disabled = true;
    pullProgressContainer.classList.remove('hidden');
    pullStatusText.textContent = 'Connecting...';
    pullProgressBar.style.width = '0%';
    pullPercentText.textContent = '0%';
    writeLog('Pulling model: ' + name);
    try {
        const res = await fetch('/api/models/pull', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name}) });
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            buf += dec.decode(value, {stream:true});
            const lines = buf.split('\n');
            buf = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const p = JSON.parse(line.slice(6).trim());
                    if (p.status === 'complete') {
                        pullStatusText.textContent = 'Complete!';
                        pullProgressBar.style.width = '100%';
                        pullPercentText.textContent = '100%';
                        writeLog('Model ' + name + ' pulled.');
                        setTimeout(() => { pullProgressContainer.classList.add('hidden'); btnPullModel.disabled = false; pullModelNameInput.value=''; }, 2500);
                    } else if (p.total) {
                        const pct = Math.round((p.completed / p.total) * 100);
                        pullProgressBar.style.width = pct + '%';
                        pullPercentText.textContent = pct + '%';
                        pullStatusText.textContent = p.status || 'Downloading...';
                    } else { pullStatusText.textContent = p.status || 'Downloading...'; }
                } catch (x) {}
            }
        }
    } catch (e) { writeLog('Pull error: ' + e.message); btnPullModel.disabled = false; }
});

// --- Native Binary Install ---
btnInstallNative.addEventListener('click', async () => {
    btnInstallNative.disabled = true;
    nativeProgressContainer.classList.remove('hidden');
    nativeStatusText.textContent = 'Fetching latest release...';
    nativeProgressBar.style.width = '0%';
    nativePercentText.textContent = '0%';
    writeLog('Installing native llama.cpp binaries...');
    try {
        const res = await fetch('/api/runner/install', { method:'POST' });
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            buf += dec.decode(value, {stream:true});
            const lines = buf.split('\n');
            buf = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const p = JSON.parse(line.slice(6).trim());
                    nativeStatusText.textContent = p.message || p.status;
                    if (p.total && p.completed) {
                        const pct = Math.round((p.completed / p.total) * 100);
                        nativeProgressBar.style.width = pct + '%';
                        nativePercentText.textContent = pct + '%';
                    }
                    if (p.status === 'complete') {
                        nativeProgressBar.style.width = '100%';
                        nativePercentText.textContent = '100%';
                        writeLog('Native binaries installed!');
                        fetchNativeStatus();
                        setTimeout(() => { nativeProgressContainer.classList.add('hidden'); btnInstallNative.disabled = false; }, 2000);
                    }
                    if (p.status === 'error') {
                        writeLog('Install error: ' + p.message);
                        btnInstallNative.disabled = false;
                    }
                } catch (x) {}
            }
        }
    } catch (e) { writeLog('Install error: ' + e.message); btnInstallNative.disabled = false; }
});

// --- Native GGUF Model Download ---
btnDownloadNativeModel.addEventListener('click', async () => {
    const modelId = nativeDownloadModelSelect.value;
    btnDownloadNativeModel.disabled = true;
    nativeProgressContainer.classList.remove('hidden');
    nativeStatusText.textContent = 'Starting GGUF download...';
    nativeProgressBar.style.width = '0%';
    nativePercentText.textContent = '0%';
    writeLog('Downloading GGUF: ' + modelId);
    try {
        const res = await fetch('/api/runner/download_model', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({model_id: modelId}) });
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            buf += dec.decode(value, {stream:true});
            const lines = buf.split('\n');
            buf = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const p = JSON.parse(line.slice(6).trim());
                    nativeStatusText.textContent = p.message || p.status;
                    if (p.total && p.completed) {
                        const pct = Math.round((p.completed / p.total) * 100);
                        nativeProgressBar.style.width = pct + '%';
                        nativePercentText.textContent = pct + '%';
                    }
                    if (p.status === 'complete') {
                        nativeProgressBar.style.width = '100%';
                        nativePercentText.textContent = '100%';
                        writeLog('GGUF download complete.');
                        fetchNativeStatus();
                        setTimeout(() => { nativeProgressContainer.classList.add('hidden'); btnDownloadNativeModel.disabled = false; }, 2000);
                    }
                    if (p.status === 'error') {
                        writeLog('GGUF download error: ' + p.message);
                        btnDownloadNativeModel.disabled = false;
                    }
                } catch (x) {}
            }
        }
    } catch (e) { writeLog('GGUF error: ' + e.message); btnDownloadNativeModel.disabled = false; }
});

// --- Native Server Start/Stop ---
btnStartNativeServer.addEventListener('click', async () => {
    const filename = nativeLocalModels.value;
    if (!filename) return alert('Select a GGUF model file first.');
    writeLog('Starting native server with: ' + filename);
    try {
        const r = await fetch('/api/runner/start', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({filename}) });
        const d = await r.json();
        writeLog(d.message || 'Server started.');
    } catch (e) { writeLog('Start error: ' + e.message); }
});
btnStopNativeServer.addEventListener('click', async () => {
    writeLog('Stopping native server...');
    try {
        const r = await fetch('/api/runner/stop', { method:'POST' });
        const d = await r.json();
        writeLog(d.message || 'Server stopped.');
    } catch (e) { writeLog('Stop error: ' + e.message); }
});

// --- Skill Creation ---
btnToggleSkillForm.addEventListener('click', () => skillCreateForm.classList.toggle('hidden'));
btnCancelSkill.addEventListener('click', () => skillCreateForm.classList.add('hidden'));

skillCreateForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
        id: document.getElementById('new-skill-id').value.trim(),
        title: document.getElementById('new-skill-title').value.trim(),
        description: document.getElementById('new-skill-desc').value.trim(),
        instructions: document.getElementById('new-skill-instructions').value.trim()
    };
    if (!payload.id || !payload.title) return alert('Skill ID and Title are required.');
    try {
        const r = await fetch('/api/skills/create', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
        if (!r.ok) throw new Error('Skill create failed');
        writeLog('Skill "' + payload.title + '" created successfully.');
        skillCreateForm.classList.add('hidden');
        skillCreateForm.reset();
        fetchSkills();
    } catch (e) { writeLog('Skill error: ' + e.message); }
});

// --- RAG Indexing ---
btnIndexNow.addEventListener('click', async () => {
    btnIndexNow.disabled = true;
    writeLog('Initiating workspace index scan...');
    try {
        const r = await fetch('/api/rag/index', { method:'POST' });
        if (!r.ok) throw new Error('Indexing failed');
        const d = await r.json();
        if (d.status === 'success') {
            const s = d.results;
            writeLog(`Indexed ${s.files_indexed} files, ${s.chunks_added} chunks. Duration: ${s.duration_seconds}s`);
            fetchStatus();
        }
    } catch (e) { writeLog('Index error: ' + e.message); }
    finally { btnIndexNow.disabled = false; }
});

btnClearIndex.addEventListener('click', async () => {
    if (!confirm('Clear the entire RAG vector index?')) return;
    try { await fetch('/api/rag/clear', {method:'POST'}); writeLog('RAG database cleared.'); fetchStatus(); }
    catch (e) { writeLog('Clear error: ' + e.message); }
});

// --- RAG Search ---
async function doRAGSearch() {
    const q = ragSearchQuery.value.trim();
    if (!q) return;
    btnRAGSearch.disabled = true;
    ragSearchResults.innerHTML = '<div class="skeleton-text">Searching...</div>';
    ragSearchResults.classList.remove('hidden');
    try {
        const r = await fetch(`/api/rag/search?query=${encodeURIComponent(q)}&limit=3`);
        const d = await r.json();
        ragSearchResults.innerHTML = '';
        if (d.results.length === 0) {
            ragSearchResults.innerHTML = '<div class="rag-result-item">No matches found.</div>';
            return;
        }
        d.results.forEach(r => {
            const el = document.createElement('div');
            el.className = 'rag-result-item';
            el.innerHTML = `<div class="rag-result-meta"><span>${r.filename} (L${r.start_line}-${r.end_line})</span><span class="score">Score: ${r.score}</span></div><pre class="rag-result-content"><code>${escapeHTML(r.content)}</code></pre>`;
            ragSearchResults.appendChild(el);
        });
    } catch (e) { ragSearchResults.innerHTML = '<div class="rag-result-item">Error: ' + e.message + '</div>'; }
    finally { btnRAGSearch.disabled = false; }
}
btnRAGSearch.addEventListener('click', doRAGSearch);
ragSearchQuery.addEventListener('keypress', e => { if (e.key === 'Enter') doRAGSearch(); });


// ============================
//  CHAT / PLAYGROUND
// ============================

btnClearChat.addEventListener('click', () => {
    chatHistory = [];
    chatMessagesEl.innerHTML = `<div class="chat-welcome"><div class="welcome-icon"><i class="fa-solid fa-robot"></i></div><h3>Welcome to LocoEngine Playground</h3><p>Select <b>Code</b>, <b>Plan</b>, or <b>Agent</b> mode to test completions.</p></div>`;
    speedIndicator.textContent = 'Speed: 0 t/s';
});

async function sendChatMessage() {
    const text = chatInput.value.trim();
    if (!text) return;
    const welcome = chatMessagesEl.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    // User bubble
    const userRow = document.createElement('div');
    userRow.className = 'message-row user';
    userRow.innerHTML = `<div class="message-bubble">${escapeHTML(text)}</div>`;
    chatMessagesEl.appendChild(userRow);
    chatInput.value = '';
    chatInput.disabled = true;
    btnSendChat.disabled = true;
    chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
    chatHistory.push({ role:'user', content:text });

    // Assistant bubble
    const aRow = document.createElement('div');
    aRow.className = 'message-row assistant';
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    aRow.appendChild(bubble);
    chatMessagesEl.appendChild(aRow);

    let cotContainer = null, cotBody = null, textBody = null;
    let isThinking = false;
    let fullText = '';
    let tokenCount = 0;
    const streamStartTime = Date.now();

    try {
        const res = await fetch('/v1/chat/completions', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({ messages: chatHistory, stream: true })
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);

        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = '';

        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            buf += dec.decode(value, {stream:true});
            const lines = buf.split('\n');
            buf = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const raw = line.slice(6).trim();
                if (raw === '[DONE]') continue;
                let parsed;
                try { parsed = JSON.parse(raw); } catch(x) { continue; }

                const delta = parsed.choices[0].delta;
                const content = delta.content || '';

                // --- Intercept approval_required signals ---
                if (delta.approval_required) {
                    const reqId = delta.req_id;
                    const cmd = delta.command || '';
                    const card = document.createElement('div');
                    card.className = 'approval-card';
                    card.innerHTML = `
                        <div class="approval-header"><i class="fa-solid fa-shield-halved"></i> Command Execution Approval Required</div>
                        <pre>${escapeHTML(cmd)}</pre>
                        <div class="approval-actions">
                            <button class="btn-approve" onclick="resolveApproval('${reqId}', true, this)"><i class="fa-solid fa-check"></i> Approve & Run</button>
                            <button class="btn-reject" onclick="resolveApproval('${reqId}', false, this)"><i class="fa-solid fa-xmark"></i> Reject</button>
                        </div>
                    `;
                    bubble.appendChild(card);
                    chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
                    continue;
                }

                if (!content) continue;
                fullText += content;
                tokenCount++;

                // Update speed
                const elapsed = (Date.now() - streamStartTime) / 1000;
                if (elapsed > 0.3) {
                    speedIndicator.textContent = `Speed: ${(tokenCount / elapsed).toFixed(1)} t/s`;
                }

                // <think> tag detection
                if (content.includes('<think>')) {
                    isThinking = true;
                    cotContainer = document.createElement('div');
                    cotContainer.className = 'cot-container';
                    const hdr = document.createElement('div');
                    hdr.className = 'cot-header';
                    hdr.innerHTML = '<span><i class="fa-solid fa-brain"></i> Thinking Process...</span> <i class="fa-solid fa-chevron-down"></i>';
                    hdr.onclick = () => cotContainer.classList.toggle('collapsed');
                    cotBody = document.createElement('div');
                    cotBody.className = 'cot-body';
                    cotContainer.appendChild(hdr);
                    cotContainer.appendChild(cotBody);
                    bubble.appendChild(cotContainer);
                    const cleaned = content.replace('<think>', '');
                    if (cleaned) cotBody.textContent += cleaned;
                } else if (isThinking && content.includes('</think>')) {
                    isThinking = false;
                    const parts = content.split('</think>');
                    if (parts[0] && cotBody) cotBody.textContent += parts[0];
                    if (cotContainer) {
                        cotContainer.classList.add('collapsed');
                        cotContainer.querySelector('.cot-header span').innerHTML = '<i class="fa-solid fa-circle-check"></i> Thinking completed';
                    }
                    textBody = document.createElement('div');
                    textBody.className = 'text-body';
                    bubble.appendChild(textBody);
                    if (parts[1]) textBody.innerHTML = formatMD(parts[1]);
                } else if (isThinking) {
                    if (cotBody) cotBody.textContent += content;
                } else {
                    if (!textBody) {
                        textBody = document.createElement('div');
                        textBody.className = 'text-body';
                        bubble.appendChild(textBody);
                    }
                    const afterThink = fullText.split('</think>').pop() || fullText;
                    textBody.innerHTML = formatMD(afterThink);
                }
                chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
            }
        }
        chatHistory.push({ role:'assistant', content:fullText });
        writeLog('Chat completed. ' + tokenCount + ' tokens.');
    } catch (e) {
        bubble.innerHTML = `<div style="color:var(--danger)"><i class="fa-solid fa-triangle-exclamation"></i> Error: ${e.message}</div>`;
        writeLog('Completion error: ' + e.message);
    } finally {
        chatInput.disabled = false;
        btnSendChat.disabled = false;
        chatInput.focus();
    }
}

function formatMD(text) {
    let s = escapeHTML(text);
    s = s.replace(/```([\w-]*)\n([\s\S]*?)```/g, (m, lang, code) => `<pre><code class="language-${lang}">${code.trim()}</code></pre>`);
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    s = s.replace(/^\s*[-*]\s+(.*)$/gm, '<li>$1</li>');
    s = s.replace(/\n\n/g, '<br><br>');
    return s;
}

// Global approval resolution function (called from HTML onclick)
window.resolveApproval = async function(reqId, approved, btnEl) {
    // Disable buttons after click
    const card = btnEl.closest('.approval-card');
    card.querySelectorAll('button').forEach(b => b.disabled = true);

    try {
        await fetch('/api/chat/approve', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({ req_id: reqId, approved })
        });
        card.querySelector('.approval-header').innerHTML = approved
            ? '<i class="fa-solid fa-circle-check" style="color:var(--success)"></i> Command Approved'
            : '<i class="fa-solid fa-circle-xmark" style="color:var(--danger)"></i> Command Rejected';
        writeLog(`Approval ${reqId}: ${approved ? 'APPROVED' : 'REJECTED'}`);
    } catch (e) {
        writeLog('Approval callback error: ' + e.message);
    }
};

btnSendChat.addEventListener('click', sendChatMessage);
chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(); }
});

// === Init ===
async function init() {
    writeLog('LocoEngine dashboard initialized.');
    await fetchConfig();
    await fetchStatus();
    await fetchSkills();
    systemStatsInterval = setInterval(fetchStatus, 3000);
}
window.onload = init;
window.onunload = () => { if (systemStatsInterval) clearInterval(systemStatsInterval); };
