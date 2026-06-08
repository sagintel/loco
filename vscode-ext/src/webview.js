/* ═══════════════════════════════════════════════════════════════
   LocoEngine VSCode Sidebar — Webview Controller
   Handles: SSE streaming, thought parsing, HITL approvals,
   markdown rendering, mode switching, context chips, settings,
   custom RAG indexing, chat history, and Native runner setup.
   ═══════════════════════════════════════════════════════════════ */

(function () {
    const vscode = acquireVsCodeApi();

    // ─── State ───
    let serverUrl = 'http://127.0.0.1:8000';
    let currentMode = 'code';
    let conversationHistory = [];
    let savedSessions = [];
    let isStreaming = false;
    let abortController = null;
    let currentActiveFile = '';
    let currentSelectedText = '';
    let workspacePath = '';
    let contextChips = [];
    let pendingApprovalReqId = null;
    let thoughtCounter = 0;

    // Restore saved state on load
    const savedState = vscode.getState() || {};
    if (savedState.conversationHistory) conversationHistory = savedState.conversationHistory;
    if (savedState.savedSessions) savedSessions = savedState.savedSessions;
    if (savedState.serverUrl) serverUrl = savedState.serverUrl;
    if (savedState.currentMode) currentMode = savedState.currentMode;

    // ─── DOM Refs ───
    const $messages       = document.getElementById('messages');
    const $chatContainer  = document.getElementById('chat-container');
    const $welcome        = document.getElementById('welcome-screen');
    const $prompt         = document.getElementById('prompt-input');
    const $btnSend        = document.getElementById('btn-send');
    const $btnStop        = document.getElementById('btn-stop');
    const $btnSettings    = document.getElementById('btn-settings');
    const $btnClear       = document.getElementById('btn-clear');
    const $btnAttachFile  = document.getElementById('btn-attach-file');
    const $btnAttachSel   = document.getElementById('btn-attach-selection');
    const $statusBadge    = document.getElementById('status-badge');
    const $statusLabel    = $statusBadge.querySelector('.status-label');
    const $wsPath         = document.getElementById('workspace-path');
    const $ctxFileLabel   = document.getElementById('ctx-file-label');
    const $footerModel    = document.getElementById('footer-model');
    const $inputChips     = document.getElementById('input-chips');
    const $approvalBanner = document.getElementById('approval-banner');
    const $approvalCmd    = document.getElementById('approval-command');
    const $btnApprove     = document.getElementById('btn-approve');
    const $btnReject      = document.getElementById('btn-reject');
    const $settingsOverlay= document.getElementById('settings-overlay');
    const $settingUrl     = document.getElementById('setting-server-url');
    const $settingCoding  = document.getElementById('setting-coding-model');
    const $settingReasoning = document.getElementById('setting-reasoning-model');
    const $settingRag     = document.getElementById('setting-rag');
    const $settingCascade = document.getElementById('setting-cascade');
    const $btnSaveSettings= document.getElementById('btn-save-settings');
    const $btnCloseSettings = document.getElementById('btn-close-settings');
    const modeBtns        = document.querySelectorAll('.mode-btn');
    const $modeIndicator  = document.getElementById('mode-indicator');

    // Added elements
    const $footerModelSelect = document.getElementById('footer-model-select');
    const $noModelOverlay = document.getElementById('no-model-overlay');
    const $btnWarningOpenSettings = document.getElementById('btn-warning-open-settings');
    const $btnHistory = document.getElementById('btn-history');
    const $historyOverlay = document.getElementById('history-overlay');
    const $btnCloseHistory = document.getElementById('btn-close-history');
    const $historyListContainer = document.getElementById('history-list-container');
    const $btnSyncSkills = document.getElementById('btn-sync-skills');

    // RAG Custom Indexing refs
    const $ragFileInput = document.getElementById('rag-file-input');
    const $btnUploadFile = document.getElementById('btn-upload-file');
    const $ragFileName = document.getElementById('rag-file-name');
    const $ragUrlInput = document.getElementById('rag-url-input');
    const $btnScrapeUrl = document.getElementById('btn-scrape-url');
    const $ragStatusMsg = document.getElementById('rag-status-msg');

    // Native Runner setup refs
    const $btnInstallRunner = document.getElementById('btn-install-runner');
    const $btnDownloadModel = document.getElementById('btn-download-model');
    const $btnStartRunner = document.getElementById('btn-start-runner');
    const $btnStopRunner = document.getElementById('btn-stop-runner');
    const $downloadSelect = document.getElementById('download-model-select');
    const $startSelect = document.getElementById('start-model-select');
    const $progressContainer = document.getElementById('download-progress-container');
    const $progressBar = document.getElementById('download-progress-bar');
    const $progressStatus = document.getElementById('download-progress-status');

    // ═══════════════════════════════════════════
    //  STATE PERSISTENCE
    // ═══════════════════════════════════════════
    function saveState() {
        vscode.setState({
            conversationHistory,
            savedSessions,
            serverUrl,
            currentMode
        });
    }

    // ═══════════════════════════════════════════
    //  STATUS MANAGEMENT
    // ═══════════════════════════════════════════
    function setStatus(status, label) {
        $statusBadge.className = 'status-badge status-' + status;
        $statusLabel.textContent = label || status.charAt(0).toUpperCase() + status.slice(1);
    }

    // ═══════════════════════════════════════════
    //  MARKDOWN RENDERER (Lightweight)
    // ═══════════════════════════════════════════
    function renderMarkdown(text) {
        if (!text) return '';
        let html = escapeHtml(text);

        // Code blocks with copy button
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
            const id = 'code-' + Math.random().toString(36).substr(2, 8);
            return `<pre id="${id}"><button class="code-copy-btn" onclick="copyCode('${id}')">Copy</button><code>${code.trim()}</code></pre>`;
        });

        // Inline code
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Headers
        html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
        html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
        html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

        // Bold and italic
        html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

        // Links
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" title="$2" target="_blank">$1</a>');

        // Blockquotes
        html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

        // Unordered lists
        html = html.replace(/^- \[x\] (.+)$/gm, '<li>✅ $1</li>');
        html = html.replace(/^- \[ \] (.+)$/gm, '<li>⬜ $1</li>');
        html = html.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
        html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

        // Ordered lists
        html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

        // Horizontal rules
        html = html.replace(/^---$/gm, '<hr>');

        // Paragraphs (double newline)
        html = html.replace(/\n\n/g, '</p><p>');
        html = html.replace(/\n/g, '<br>');

        return '<p>' + html + '</p>';
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    window.copyCode = function(id) {
        const el = document.getElementById(id);
        if (el) {
            const code = el.querySelector('code').textContent;
            navigator.clipboard.writeText(code).then(() => {
                const btn = el.querySelector('.code-copy-btn');
                btn.textContent = 'Copied!';
                setTimeout(() => btn.textContent = 'Copy', 1500);
            });
        }
    };

    // ─── Thought & Plan Parser ───
    function parseAssistantContent(rawText) {
        const container = document.createDocumentFragment();
        let remaining = rawText;

        const thinkRegex = /<think>([\s\S]*?)<\/think>/g;
        let lastIndex = 0;
        let match;

        const parts = [];
        while ((match = thinkRegex.exec(remaining)) !== null) {
            if (match.index > lastIndex) {
                parts.push({ type: 'text', content: remaining.slice(lastIndex, match.index) });
            }
            parts.push({ type: 'think', content: match[1].trim() });
            lastIndex = thinkRegex.lastIndex;
        }
        if (lastIndex < remaining.length) {
            parts.push({ type: 'text', content: remaining.slice(lastIndex) });
        }

        if (parts.length === 1 && parts[0].type === 'text') {
            const reactParsed = parseReActBlocks(parts[0].content);
            reactParsed.forEach(part => {
                container.appendChild(renderPart(part));
            });
        } else {
            parts.forEach(part => {
                container.appendChild(renderPart(part));
            });
        }

        return container;
    }

    function parseReActBlocks(text) {
        const parts = [];
        const lines = text.split('\n');
        let currentThought = null;
        let regularBuffer = [];
        let inFinalAnswer = false;
        let finalBuffer = [];

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];

            if (line.startsWith('Thought:')) {
                if (regularBuffer.length > 0) {
                    parts.push({ type: 'text', content: regularBuffer.join('\n') });
                    regularBuffer = [];
                }
                if (currentThought) {
                    parts.push(currentThought);
                }
                currentThought = { type: 'thought', title: line.replace('Thought:', '').trim(), content: '' };
                inFinalAnswer = false;
            } else if (line.startsWith('Action:') && currentThought) {
                currentThought.content += line + '\n';
            } else if (line.startsWith('Arguments:') && currentThought) {
                currentThought.content += line + '\n';
            } else if (line.startsWith('Final Answer:')) {
                if (currentThought) {
                    parts.push(currentThought);
                    currentThought = null;
                }
                if (regularBuffer.length > 0) {
                    parts.push({ type: 'text', content: regularBuffer.join('\n') });
                    regularBuffer = [];
                }
                inFinalAnswer = true;
                const answerText = line.replace('Final Answer:', '').trim();
                if (answerText) finalBuffer.push(answerText);
            } else if (line.match(/^\*Observation:\*/) || line.startsWith('Observation:')) {
                if (currentThought) {
                    currentThought.content += line + '\n';
                } else {
                    regularBuffer.push(line);
                }
            } else if (inFinalAnswer) {
                finalBuffer.push(line);
            } else if (currentThought) {
                currentThought.content += line + '\n';
            } else {
                regularBuffer.push(line);
            }
        }

        if (currentThought) parts.push(currentThought);
        if (regularBuffer.length > 0) parts.push({ type: 'text', content: regularBuffer.join('\n') });
        if (finalBuffer.length > 0) parts.push({ type: 'summary', content: finalBuffer.join('\n') });

        return parts;
    }

    function renderPart(part) {
        if (part.type === 'think') {
            return createThoughtBlock(part.content, 'Reasoning');
        } else if (part.type === 'thought') {
            return createThoughtBlock(part.content, part.title);
        } else if (part.type === 'plan') {
            return createPlanBlock(part.content, part.title);
        } else if (part.type === 'summary') {
            return createSummaryBlock(part.content);
        } else {
            const text = part.content.trim();
            if (text.match(/^(## )?(\d+\.\s|Step \d+|Phase \d+)/im) && text.includes('- [ ]')) {
                return createPlanBlock(text, 'Implementation Plan');
            }
            const div = document.createElement('div');
            div.innerHTML = renderMarkdown(text);
            return div;
        }
    }

    function createThoughtBlock(content, title) {
        thoughtCounter++;
        const block = document.createElement('div');
        block.className = 'thought-block';
        const shortTitle = title.length > 60 ? title.substring(0, 57) + '...' : title;
        block.innerHTML = `
            <div class="thought-header" onclick="this.parentElement.classList.toggle('expanded')">
                <span class="thought-caret">▶</span>
                <span class="thought-title">${escapeHtml(shortTitle)}</span>
                <span class="thought-step-badge">Step ${thoughtCounter}</span>
            </div>
            <div class="thought-content">${renderMarkdown(content)}</div>
        `;
        return block;
    }

    function createPlanBlock(content, title) {
        const block = document.createElement('div');
        block.className = 'plan-block';
        block.innerHTML = `
            <div class="plan-header" onclick="this.parentElement.classList.toggle('expanded')">
                <span class="thought-caret">▶</span>
                <span>📋 ${escapeHtml(title || 'Plan')}</span>
            </div>
            <div class="plan-content">${renderMarkdown(content)}</div>
        `;
        return block;
    }

    function createSummaryBlock(content) {
        const block = document.createElement('div');
        block.className = 'summary-block';
        block.innerHTML = `<div class="summary-title">✅ Summary</div>${renderMarkdown(content)}`;
        return block;
    }

    // ═══════════════════════════════════════════
    //  MESSAGE RENDERING
    // ═══════════════════════════════════════════
    function addUserMessage(text) {
        $welcome.classList.add('hidden');
        const msg = document.createElement('div');
        msg.className = 'msg user';
        msg.innerHTML = `
            <div class="msg-header user-header">
                <span class="msg-avatar">👤</span>
                <span>You</span>
            </div>
            <div class="msg-body">${renderMarkdown(text)}</div>
        `;
        $messages.appendChild(msg);
        scrollToBottom();
    }

    function createAssistantMessage() {
        $welcome.classList.add('hidden');
        const msg = document.createElement('div');
        msg.className = 'msg assistant';
        msg.innerHTML = `
            <div class="msg-header assistant-header">
                <span class="msg-avatar">⚡</span>
                <span>LocoEngine</span>
            </div>
            <div class="msg-body">
                <div class="loading-dots"><span></span><span></span><span></span></div>
            </div>
        `;
        $messages.appendChild(msg);
        scrollToBottom();
        return msg.querySelector('.msg-body');
    }

    function finalizeAssistantMessage(bodyEl, rawText) {
        bodyEl.innerHTML = '';
        const parsed = parseAssistantContent(rawText);
        bodyEl.appendChild(parsed);
        scrollToBottom();
    }

    function scrollToBottom() {
        requestAnimationFrame(() => {
            $chatContainer.scrollTop = $chatContainer.scrollHeight;
        });
    }

    // ═══════════════════════════════════════════
    //  SSE STREAMING ENGINE
    // ═══════════════════════════════════════════
    async function sendMessage(userText) {
        if (isStreaming || !userText.trim()) return;

        let contextPrefix = '';
        if (contextChips.length > 0) {
            contextPrefix = contextChips.map(c => {
                if (c.type === 'file') return `[Context: File "${c.label}"]\n`;
                if (c.type === 'selection') return `[Context: Selected code from "${c.label}"]\n\`\`\`\n${c.content}\n\`\`\`\n`;
                return '';
            }).join('');
            clearChips();
        }

        const fullPrompt = contextPrefix + userText;

        addUserMessage(userText);
        conversationHistory.push({ role: 'user', content: fullPrompt });
        saveState();

        isStreaming = true;
        abortController = new AbortController();
        $btnSend.classList.add('hidden');
        $btnStop.classList.remove('hidden');
        setStatus('thinking', 'Thinking');
        thoughtCounter = 0;

        const bodyEl = createAssistantMessage();
        let accumulated = '';

        try {
            const response = await fetch(serverUrl + '/v1/chat/completions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    messages: conversationHistory,
                    stream: true
                }),
                signal: abortController.signal
            });

            if (!response.ok) {
                throw new Error(`Server responded with ${response.status}: ${response.statusText}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const payload = line.slice(6).trim();
                    if (payload === '[DONE]') continue;

                    try {
                        const data = JSON.parse(payload);
                        const delta = data.choices?.[0]?.delta || {};
                        const finishReason = data.choices?.[0]?.finish_reason;

                        if (delta.approval_required) {
                            setStatus('approving', 'Approval');
                            pendingApprovalReqId = delta.req_id;
                            $approvalCmd.textContent = delta.command || 'Unknown action';
                            $approvalBanner.classList.remove('hidden');
                        }

                        if (delta.content) {
                            accumulated += delta.content;
                            bodyEl.innerHTML = renderMarkdown(accumulated);
                            scrollToBottom();

                            if (delta.content.includes('Action:') || delta.content.includes('write_file') || delta.content.includes('Executing')) {
                                setStatus('editing', 'Editing');
                            }
                        }

                        if (finishReason === 'stop') break;
                    } catch (e) {}
                }
            }
        } catch (err) {
            if (err.name === 'AbortError') {
                accumulated += '\n\n*Generation stopped by user.*';
            } else {
                accumulated = `**Connection Error**: ${err.message}\n\nMake sure the LocoEngine server is running at \`${serverUrl}\`.`;
                setStatus('error', 'Offline');
            }
        }

        finalizeAssistantMessage(bodyEl, accumulated);
        conversationHistory.push({ role: 'assistant', content: accumulated });
        saveState();

        isStreaming = false;
        abortController = null;
        $btnSend.classList.remove('hidden');
        $btnStop.classList.add('hidden');
        if ($statusBadge.className.includes('error') === false) {
            setStatus('idle', 'Idle');
        }
    }

    // ═══════════════════════════════════════════
    //  HITL APPROVAL
    // ═══════════════════════════════════════════
    async function resolveApproval(approved) {
        if (!pendingApprovalReqId) return;
        try {
            await fetch(serverUrl + '/api/chat/approve', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ req_id: pendingApprovalReqId, approved })
            });
        } catch (e) {
            console.error('Failed to send approval:', e);
        }
        pendingApprovalReqId = null;
        $approvalBanner.classList.add('hidden');
        setStatus(approved ? 'editing' : 'idle', approved ? 'Editing' : 'Idle');
    }

    $btnApprove.addEventListener('click', () => resolveApproval(true));
    $btnReject.addEventListener('click', () => resolveApproval(false));

    // ═══════════════════════════════════════════
    //  CONTEXT CHIPS
    // ═══════════════════════════════════════════
    function addChip(type, label, content) {
        const existing = contextChips.find(c => c.type === type && c.label === label);
        if (existing) return;
        contextChips.push({ type, label, content });
        renderChips();
    }

    function removeChip(index) {
        contextChips.splice(index, 1);
        renderChips();
    }

    function clearChips() {
        contextChips = [];
        renderChips();
    }

    function renderChips() {
        $inputChips.innerHTML = '';
        contextChips.forEach((chip, i) => {
            const el = document.createElement('span');
            el.className = 'input-chip';
            const icon = chip.type === 'file' ? '📄' : '✂️';
            el.innerHTML = `${icon} ${escapeHtml(chip.label)} <span class="chip-remove" data-index="${i}">×</span>`;
            $inputChips.appendChild(el);
        });
        $inputChips.querySelectorAll('.chip-remove').forEach(btn => {
            btn.addEventListener('click', () => removeChip(parseInt(btn.dataset.index)));
        });
    }

    $btnAttachFile.addEventListener('click', () => {
        if (currentActiveFile) addChip('file', currentActiveFile, '');
    });

    $btnAttachSel.addEventListener('click', () => {
        if (currentSelectedText && currentActiveFile) addChip('selection', currentActiveFile, currentSelectedText);
    });

    // ═══════════════════════════════════════════
    //  MODE SWITCHING
    // ═══════════════════════════════════════════
    modeBtns.forEach((btn, idx) => {
        btn.addEventListener('click', () => {
            modeBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentMode = btn.dataset.mode;
            $modeIndicator.style.transform = `translateX(${idx * 100}%)`;
            saveState();

            fetch(serverUrl + '/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ gateway_mode: currentMode })
            }).catch(() => {});
        });
    });

    // ═══════════════════════════════════════════
    //  INPUT HANDLING
    // ═══════════════════════════════════════════
    $prompt.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage($prompt.value);
            $prompt.value = '';
            $prompt.style.height = 'auto';
        }
    });

    $prompt.addEventListener('input', () => {
        $prompt.style.height = 'auto';
        $prompt.style.height = Math.min($prompt.scrollHeight, 120) + 'px';
    });

    $btnSend.addEventListener('click', () => {
        sendMessage($prompt.value);
        $prompt.value = '';
        $prompt.style.height = 'auto';
    });

    $btnStop.addEventListener('click', () => {
        if (abortController) abortController.abort();
    });

    $btnClear.addEventListener('click', () => {
        if (conversationHistory.length > 0) addCurrentSessionToHistory();
        conversationHistory = [];
        $messages.innerHTML = '';
        $welcome.classList.remove('hidden');
        thoughtCounter = 0;
        setStatus('idle', 'Idle');
        saveState();
    });

    // ═══════════════════════════════════════════
    //  SETTINGS & NATIVE RUNNER Downloader
    // ═══════════════════════════════════════════
    $btnSettings.addEventListener('click', () => {
        $settingsOverlay.classList.remove('hidden');
        loadSettings();
    });

    $btnCloseSettings.addEventListener('click', () => $settingsOverlay.classList.add('hidden'));

    $settingsOverlay.addEventListener('click', (e) => {
        if (e.target === $settingsOverlay) $settingsOverlay.classList.add('hidden');
    });

    async function loadSettings() {
        try {
            const [configRes, modelsRes] = await Promise.all([
                fetch(serverUrl + '/api/config').then(r => r.json()),
                fetch(serverUrl + '/api/models').then(r => r.json()).catch(() => ({ models: [] }))
            ]);

            $settingUrl.value = serverUrl;
            $settingRag.checked = configRes.enable_rag !== false;
            $settingCascade.checked = configRes.enable_cascade !== false;

            const models = modelsRes.models || [];
            const modelNames = models.map(m => m.name || m.id || m);

            populateSelect($settingCoding, modelNames, configRes.coding_model);
            populateSelect($settingReasoning, modelNames, configRes.reasoning_model);
            updateStatusAndModels();
        } catch (e) {
            console.error('Failed to load settings:', e);
        }
    }

    function populateSelect(selectEl, options, selected) {
        selectEl.innerHTML = '';
        if (options.length === 0) {
            const opt = document.createElement('option');
            opt.textContent = 'No models found';
            selectEl.appendChild(opt);
            return;
        }
        options.forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            if (name === selected) opt.selected = true;
            selectEl.appendChild(opt);
        });
    }

    $btnSaveSettings.addEventListener('click', async () => {
        const newUrl = $settingUrl.value.trim().replace(/\/+$/, '');
        serverUrl = newUrl;
        saveState();

        try {
            await fetch(serverUrl + '/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    coding_model: $settingCoding.value,
                    reasoning_model: $settingReasoning.value,
                    enable_rag: $settingRag.checked,
                    enable_cascade: $settingCascade.checked
                })
            });
            vscode.postMessage({ type: 'saveSettings', serverUrl: newUrl });
            vscode.postMessage({ type: 'showInfoMessage', message: 'LocoEngine settings saved successfully.' });
        } catch (e) {
            vscode.postMessage({ type: 'showErrorMessage', message: 'Failed to save settings: ' + e.message });
        }
        $settingsOverlay.classList.add('hidden');
        updateStatusAndModels();
    });

    // ═══════════════════════════════════════════
    //  RAG DATA SOURCES CONTROLLER
    // ═══════════════════════════════════════════
    $btnUploadFile.addEventListener('click', () => $ragFileInput.click());

    $ragFileInput.addEventListener('change', async () => {
        const file = $ragFileInput.files[0];
        if (!file) return;

        $ragFileName.textContent = file.name;
        showRagStatus('Reading file...', false);

        const reader = new FileReader();
        reader.onload = async (e) => {
            const content = e.target.result;
            showRagStatus('Indexing file contents and generating embeddings...', false);
            try {
                const res = await fetch(serverUrl + '/api/rag/add_file', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filename: file.name, content })
                }).then(r => r.json());

                if (res.status === 'success') {
                    showRagStatus(`File "${file.name}" indexed successfully! (${res.chunks_added} chunks)`, false);
                } else {
                    showRagStatus('Failed to index file: ' + (res.detail || 'Unknown error'), true);
                }
            } catch (err) {
                showRagStatus('Connection error: ' + err.message, true);
            }
        };
        reader.onerror = () => showRagStatus('Failed to read file.', true);
        reader.readAsText(file);
    });

    $btnScrapeUrl.addEventListener('click', async () => {
        const url = $ragUrlInput.value.trim();
        if (!url) return;

        showRagStatus('Scraping URL page and indexing content...', false);
        try {
            const res = await fetch(serverUrl + '/api/rag/add_url', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url })
            }).then(r => r.json());

            if (res.status === 'success') {
                showRagStatus(`URL content indexed successfully! (${res.chunks_added} chunks)`, false);
                $ragUrlInput.value = '';
            } else {
                showRagStatus('Failed to index URL: ' + (res.detail || 'Unknown error'), true);
            }
        } catch (err) {
            showRagStatus('Scraper error: ' + err.message, true);
        }
    });

    function showRagStatus(msg, isError) {
        $ragStatusMsg.textContent = msg;
        $ragStatusMsg.style.display = 'block';
        if (isError) {
            $ragStatusMsg.classList.add('error');
        } else {
            $ragStatusMsg.classList.remove('error');
        }
        setTimeout(() => {
            $ragStatusMsg.style.display = 'none';
        }, 5000);
    }

    // ═══════════════════════════════════════════
    //  PERSISTENT CHAT HISTORY
    // ═══════════════════════════════════════════
    function addCurrentSessionToHistory() {
        if (conversationHistory.length === 0) return;

        let title = 'Chat Session';
        const firstUserMsg = conversationHistory.find(m => m.role === 'user');
        if (firstUserMsg) {
            title = firstUserMsg.content.slice(0, 40) + (firstUserMsg.content.length > 40 ? '...' : '');
            title = title.replace(/\[Context:.*?\]\n?/g, '');
        }

        const session = {
            id: 'session-' + Date.now(),
            title: title.trim(),
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            messages: [...conversationHistory]
        };

        savedSessions.unshift(session);
        if (savedSessions.length > 30) savedSessions.pop();

        saveState();
        renderHistoryList();
    }

    function renderHistoryList() {
        $historyListContainer.innerHTML = '';

        if (savedSessions.length === 0) {
            $historyListContainer.innerHTML = '<div class="no-history-msg">No recent activity.</div>';
            return;
        }

        savedSessions.forEach(session => {
            const item = document.createElement('div');
            item.className = 'history-item';
            item.innerHTML = `
                <div class="history-item-title">${escapeHtml(session.title)}</div>
                <div class="history-item-meta">
                    <span>💬 ${session.messages.length} messages</span>
                    <span>${session.timestamp}</span>
                </div>
            `;
            item.addEventListener('click', () => {
                if (conversationHistory.length > 0) {
                    addCurrentSessionToHistory();
                }

                conversationHistory = [...session.messages];
                $messages.innerHTML = '';
                $welcome.classList.add('hidden');

                conversationHistory.forEach(msg => {
                    if (msg.role === 'user') {
                        const renderContent = msg.content.replace(/\[Context:.*?\]\n?/g, '').replace(/```\n[\s\S]*?\n```\n?/g, '');
                        addUserMessage(renderContent);
                    } else {
                        const bodyEl = createAssistantMessage();
                        finalizeAssistantMessage(bodyEl, msg.content);
                    }
                });

                $historyOverlay.classList.add('hidden');
                saveState();
            });
            $historyListContainer.appendChild(item);
        });
    }

    $btnHistory.addEventListener('click', () => {
        $historyOverlay.classList.remove('hidden');
        renderHistoryList();
    });

    $btnCloseHistory.addEventListener('click', () => $historyOverlay.classList.add('hidden'));

    $historyOverlay.addEventListener('click', (e) => {
        if (e.target === $historyOverlay) $historyOverlay.classList.add('hidden');
    });

    // ═══════════════════════════════════════════
    //  NATIVE Downloader & Hardware Gating
    // ═══════════════════════════════════════════
    $btnInstallRunner.addEventListener('click', async () => {
        $btnInstallRunner.disabled = true;
        document.getElementById('runner-bin-status').textContent = 'Installing llama.cpp...';
        try {
            const response = await fetch(serverUrl + '/api/runner/install', { method: 'POST' });
            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const payload = line.slice(6).trim();
                    try {
                        const data = JSON.parse(payload);
                        document.getElementById('runner-bin-status').textContent = data.message;
                    } catch (e) {}
                }
            }
            vscode.postMessage({ type: 'showInfoMessage', message: 'llama.cpp binaries installed successfully.' });
        } catch (err) {
            vscode.postMessage({ type: 'showErrorMessage', message: 'Failed to install: ' + err.message });
        }
        $btnInstallRunner.disabled = false;
        updateStatusAndModels();
    });

    $btnDownloadModel.addEventListener('click', async () => {
        const modelId = $downloadSelect.value;
        $btnDownloadModel.disabled = true;
        $progressContainer.classList.remove('hidden');
        $progressBar.style.width = '0%';
        $progressStatus.textContent = 'Checking hardware gating...';

        try {
            const comp = await fetch(serverUrl + `/api/runner/check_compatibility?model_id=${modelId}`).then(r => r.json());
            if (!comp.compatible) {
                const reasons = comp.reasons.join('\n');
                vscode.postMessage({ type: 'showErrorMessage', message: 'Hardware check failed:\n' + reasons });
                $progressContainer.classList.add('hidden');
                $btnDownloadModel.disabled = false;
                return;
            }

            const response = await fetch(serverUrl + '/api/runner/download_model', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model_id: modelId })
            });

            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const payload = line.slice(6).trim();
                    try {
                        const data = JSON.parse(payload);
                        $progressStatus.textContent = data.message;
                        if (data.status === 'downloading' && data.total > 0) {
                            const pct = Math.round((data.completed / data.total) * 100);
                            $progressBar.style.width = pct + '%';
                            $progressStatus.textContent = `Downloading: ${pct}% (${(data.completed / (1024 * 1024)).toFixed(1)} / ${(data.total / (1024 * 1024)).toFixed(1)} MB)`;
                        }
                    } catch (e) {}
                }
            }
            vscode.postMessage({ type: 'showInfoMessage', message: `Model ${modelId} downloaded successfully.` });
        } catch (err) {
            vscode.postMessage({ type: 'showErrorMessage', message: 'Failed to download: ' + err.message });
        }

        $progressContainer.classList.add('hidden');
        $btnDownloadModel.disabled = false;
        updateStatusAndModels();
    });

    $btnStartRunner.addEventListener('click', async () => {
        const filename = $startSelect.value;
        if (!filename || filename.includes('No downloaded models')) return;

        $btnStartRunner.disabled = true;
        try {
            const res = await fetch(serverUrl + '/api/runner/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename })
            }).then(r => r.json());

            vscode.postMessage({ type: 'showInfoMessage', message: res.message });
        } catch (err) {
            vscode.postMessage({ type: 'showErrorMessage', message: 'Failed to start: ' + err.message });
        }
        $btnStartRunner.disabled = false;
        updateStatusAndModels();
    });

    $btnStopRunner.addEventListener('click', async () => {
        $btnStopRunner.disabled = true;
        try {
            const res = await fetch(serverUrl + '/api/runner/stop', { method: 'POST' }).then(r => r.json());
            vscode.postMessage({ type: 'showInfoMessage', message: res.message });
        } catch (err) {
            vscode.postMessage({ type: 'showErrorMessage', message: 'Failed to stop: ' + err.message });
        }
        $btnStopRunner.disabled = false;
        updateStatusAndModels();
    });

    $btnSyncSkills.addEventListener('click', async () => {
        $btnSyncSkills.disabled = true;
        $btnSyncSkills.textContent = 'Syncing...';
        try {
            const res = await fetch(serverUrl + '/api/skills/sync', { method: 'POST' }).then(r => r.json());
            if (res.status === 'success' || res.status === 'partial_success') {
                const count = res.downloaded ? res.downloaded.length : 0;
                vscode.postMessage({
                    type: 'showInfoMessage',
                    message: `Skills synced successfully! Cached ${count} Anthropic agent skills.`
                });
            } else {
                vscode.postMessage({ type: 'showErrorMessage', message: 'Sync completed with warning.' });
            }
        } catch (err) {
            vscode.postMessage({ type: 'showErrorMessage', message: 'Failed to sync skills: ' + err.message });
        }
        $btnSyncSkills.disabled = false;
        $btnSyncSkills.textContent = '🔄 Sync Skills';
    });

    $btnWarningOpenSettings.addEventListener('click', () => {
        $settingsOverlay.classList.remove('hidden');
        loadSettings();
    });

    // ═══════════════════════════════════════════
    //  MODEL CHANGER FOOTER
    // ═══════════════════════════════════════════
    $footerModelSelect.addEventListener('change', async () => {
        const val = $footerModelSelect.value;
        if (val === 'auto') return;
        try {
            await fetch(serverUrl + '/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    coding_model: val,
                    reasoning_model: val
                })
            });
            $footerModel.textContent = 'model: ' + val;
        } catch (e) {}
    });

    // ═══════════════════════════════════════════
    //  STATUS MONITOR & DYNAMIC ROUTING
    // ═══════════════════════════════════════════
    async function updateStatusAndModels() {
        try {
            const [statusRes, configRes, runnerRes] = await Promise.all([
                fetch(serverUrl + '/api/status').then(r => r.json()),
                fetch(serverUrl + '/api/config').then(r => r.json()),
                fetch(serverUrl + '/api/runner/status').then(r => r.json())
            ]);

            $wsPath.textContent = statusRes.workspace_dir ? statusRes.workspace_dir.split(/[\\/]/).pop() : 'No workspace';
            $wsPath.title = statusRes.workspace_dir || '';

            const ollamaModels = (statusRes.ollama_status === 'online') ? await fetch(serverUrl + '/api/models').then(r => r.json()).then(r => r.models || []).catch(() => []) : [];
            const nativeModels = runnerRes.downloaded_models || [];

            const currentSelected = $footerModelSelect.value;
            $footerModelSelect.innerHTML = '<option value="auto">Auto Select</option>';

            let allModelNames = [];
            ollamaModels.forEach(m => {
                const name = m.name || m;
                allModelNames.push({ name, source: 'ollama' });
            });
            nativeModels.forEach(m => {
                allModelNames.push({ name: m.name, source: 'native' });
            });

            allModelNames.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.name;
                opt.textContent = `${m.name.slice(0,25)} (${m.source})`;
                if (m.name === currentSelected) opt.selected = true;
                $footerModelSelect.appendChild(opt);
            });

            const hasModels = allModelNames.length > 0;
            if (!hasModels) {
                $noModelOverlay.classList.remove('hidden');
                $prompt.disabled = true;
                $btnSend.disabled = true;
                $footerModel.textContent = 'model: none';
            } else {
                $noModelOverlay.classList.add('hidden');
                $prompt.disabled = false;
                $btnSend.disabled = false;
                if (currentSelected === 'auto' || !currentSelected) {
                    $footerModel.textContent = 'model: auto (' + allModelNames[0].name.slice(0, 15) + ')';
                } else {
                    $footerModel.textContent = 'model: ' + currentSelected.slice(0, 20);
                }
            }

            if (runnerRes.is_installed) {
                document.getElementById('runner-bin-status').textContent = 'llama.cpp: installed';
                $btnInstallRunner.textContent = 'Reinstall';
            } else {
                document.getElementById('runner-bin-status').textContent = 'llama.cpp: not found';
                $btnInstallRunner.textContent = 'Install';
            }

            $startSelect.innerHTML = '';
            if (nativeModels.length === 0) {
                const opt = document.createElement('option');
                opt.textContent = 'No downloaded models';
                $startSelect.appendChild(opt);
            } else {
                nativeModels.forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = m.name;
                    opt.textContent = m.name;
                    $startSelect.appendChild(opt);
                });
            }

            if (runnerRes.is_running) {
                $btnStartRunner.classList.add('hidden');
                $btnStopRunner.classList.remove('hidden');
                setStatus('idle', 'Running (native)');
            } else {
                $btnStartRunner.classList.remove('hidden');
                $btnStopRunner.classList.add('hidden');
                if (statusRes.ollama_status === 'online') {
                    setStatus('idle', 'Running (Ollama)');
                } else {
                    setStatus('error', 'Offline');
                }
            }
        } catch (e) {
            console.error('Failed to update status:', e);
            setStatus('error', 'Offline');
            $noModelOverlay.classList.remove('hidden');
            $prompt.disabled = true;
            $btnSend.disabled = true;
            $footerModel.textContent = 'model: offline';
        }
    }

    // ═══════════════════════════════════════════
    //  VSCODE MESSAGE HANDLING
    // ═══════════════════════════════════════════
    window.addEventListener('message', (event) => {
        const msg = event.data;
        switch (msg.type) {
            case 'workspaceContext':
                workspacePath = msg.folderPath || '';
                currentActiveFile = msg.activeFile || '';
                currentSelectedText = msg.selectedText || '';
                $wsPath.textContent = msg.folderName || 'No workspace';
                $wsPath.title = msg.folderPath || '';
                $ctxFileLabel.textContent = msg.activeFile || 'No file active';
                break;
            case 'activeEditorChanged':
                currentActiveFile = msg.activeFile || '';
                currentSelectedText = msg.selectedText || '';
                $ctxFileLabel.textContent = msg.activeFile || 'No file active';
                break;
            case 'addSelection':
                if (msg.text) {
                    addChip('selection', msg.filePath, msg.text);
                    $prompt.focus();
                }
                break;
            case 'settings':
                serverUrl = msg.serverUrl || 'http://127.0.0.1:8000';
                break;
        }
    });

    // ═══════════════════════════════════════════
    //  INITIALIZATION
    // ═══════════════════════════════════════════
    function init() {
        vscode.postMessage({ type: 'getWorkspaceContext' });
        vscode.postMessage({ type: 'getSettings' });

        // Populate history on reload
        renderHistoryList();

        // Populate chat messages on reload
        if (conversationHistory.length > 0) {
            $welcome.classList.add('hidden');
            conversationHistory.forEach(msg => {
                if (msg.role === 'user') {
                    const renderContent = msg.content.replace(/\[Context:.*?\]\n?/g, '').replace(/```\n[\s\S]*?\n```\n?/g, '');
                    addUserMessage(renderContent);
                } else {
                    const bodyEl = createAssistantMessage();
                    finalizeAssistantMessage(bodyEl, msg.content);
                }
            });
        }

        // Initial fetch
        updateStatusAndModels();
        // Keep updated every 4s
        setInterval(updateStatusAndModels, 4000);
    }

    init();
})();
