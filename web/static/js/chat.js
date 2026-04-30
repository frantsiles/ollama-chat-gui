
/**
 * Chat module - handles messages, input, and rendering
 */

const Chat = {
    messagesContainer: null,
    messagesEl: null,
    inputEl: null,
    sendBtn: null,
    attachBtn: null,
    fileInput: null,
    attachmentsPreview: null,
    welcomeMessage: null,
    
    attachments: [],
    isProcessing: false,
    streamingMessage: null,

    /**
     * Initialize chat module
     */
    init() {
        this.messagesContainer = document.getElementById('messages-container');
        this.messagesEl = document.getElementById('messages');
        this.inputEl = document.getElementById('message-input');
        this.sendBtn = document.getElementById('send-btn');
        this.attachBtn = document.getElementById('attach-btn');
        this.fileInput = document.getElementById('file-input');
        this.attachmentsPreview = document.getElementById('attachments-preview');
        this.welcomeMessage = document.getElementById('welcome-message');

        this.bindEvents();
        this.setupWebSocketHandlers();
    },

    /**
     * Bind DOM events
     */
    bindEvents() {
        // Send button
        this.sendBtn.addEventListener('click', () => this.sendMessage());

        // Input textarea
        this.inputEl.addEventListener('input', () => {
            Utils.autoResizeTextarea(this.inputEl);
            this.updateSendButton();
        });

        this.inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        // Clipboard paste: capture screenshots and files alongside text.
        this.inputEl.addEventListener('paste', (e) => this.handlePaste(e));

        // Attach button
        this.attachBtn.addEventListener('click', () => {
            this.fileInput.click();
        });

        // File input
        this.fileInput.addEventListener('change', (e) => {
            this.handleFileSelect(e.target.files);
            this.fileInput.value = '';
        });

        // Drag and drop
        this.inputEl.parentElement.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.currentTarget.classList.add('drag-over');
        });

        this.inputEl.parentElement.addEventListener('dragleave', (e) => {
            e.currentTarget.classList.remove('drag-over');
        });

        this.inputEl.parentElement.addEventListener('drop', (e) => {
            e.preventDefault();
            e.currentTarget.classList.remove('drag-over');
            this.handleFileSelect(e.dataTransfer.files);
        });

        // New chat button
        document.getElementById('new-chat-btn').addEventListener('click', () => {
            this.clearChat();
        });
    },

    /**
     * Setup WebSocket message handlers
     */
    setupWebSocketHandlers() {
        wsManager.on('connected', (data) => {
            if (data.messages && data.messages.length > 0) {
                this.hideWelcome();
                data.messages.forEach(msg => this.renderMessage(msg));
            }
        });

        wsManager.on('start', () => {
            this.isProcessing = true;
            this.showTypingIndicator();
            this._startProcessingTimeout(120);
        });

        wsManager.on('response', (data) => {
            this.isProcessing = false;
            this.hideTypingIndicator();
            this._clearProcessingTimeout();

            if (data.status === 'cancelled') {
                this.renderMessage({
                    role: 'assistant',
                    content: '⚠️ ' + (data.content || 'Ejecución cancelada.'),
                    timestamp: new Date().toISOString()
                });
                return;
            }

            // El agente retornó error pero con type=response (fallo interno del loop)
            if (data.status === 'error') {
                this.renderMessage({
                    role: 'assistant',
                    content: '⚠️ ' + (data.error || data.content || 'El agente encontró un error. Inténtalo de nuevo.'),
                    timestamp: new Date().toISOString()
                });
                if (data.trace && data.trace.length > 0) Sidebar.updateTrace(data.trace);
                return;
            }

            // Respuesta normal (completed, max_steps, awaiting_approval)
            const content = data.content || (data.status === 'max_steps'
                ? `Se alcanzó el límite de pasos del agente. Puedes continuar enviando otro mensaje.`
                : null);

            if (content) {
                this.renderMessage({
                    role: 'assistant',
                    content,
                    timestamp: new Date().toISOString()
                });
            }

            if (data.trace && data.trace.length > 0) {
                Sidebar.updateTrace(data.trace);
            }

            if (data.token_usage && window.Sidebar) {
                Sidebar.updateContext(data.token_usage, data.message_count);
            }

            if (data.tool_results && data.tool_results.length > 0) {
                data.tool_results.forEach(result => {
                    this.renderToolCall(result);
                });
            }

            // Notificar al panel de historial para actualizar la entrada
            if (window.History && wsManager?.sessionId) {
                History.onSessionSaved({
                    id: wsManager.sessionId,
                    message_count: data.message_count,
                    model: App.state.model,
                    mode: App.state.mode,
                });
            }
        });

        wsManager.on('stream_start', () => {
            this.isProcessing = true;
            this.streamingMessage = this.createStreamingMessage();
        });

        wsManager.on('stream_chunk', (data) => {
            if (this.streamingMessage && data.content) {
                this.appendToStreamingMessage(data.content);
            }
        });

        wsManager.on('stream_end', (data) => {
            this.isProcessing = false;
            this._clearProcessingTimeout();
            this.finalizeStreamingMessage(data.content);
        });

        wsManager.on('error', (data) => {
            this.isProcessing = false;
            this.hideTypingIndicator();
            this._clearProcessingTimeout();
            this.renderMessage({
                role: 'assistant',
                content: `⚠️ ${data.message || 'Error al procesar la solicitud.'}`,
                timestamp: new Date().toISOString()
            });
        });

        wsManager.on('agent_step', (data) => {
            this.updateTypingStep(data.message);
        });

        wsManager.on('cancelled', (data) => {
            // Confirmación visual de que la cancelación fue recibida
            this.updateTypingStep('⏸️ Cancelando...');
        });

        wsManager.on('approval_required', (data) => {
            this.showTypingIndicator();
            this.updateTypingStep('⏳ Esperando aprobación...');
            this.showApprovalModal(data.pending);
        });

        wsManager.on('plan_created', (data) => {
            this.isProcessing = false;
            this.hideTypingIndicator();
            Plan.showPlan(data.plan);
        });

        wsManager.on('rag_suggestion', (data) => {
            if (data.suggestions && data.suggestions.length > 0) {
                this._showRagSuggestions(data.suggestions);
            }
        });

        wsManager.on('connectionChange', (status) => {
            if (status === 'disconnected' && this.isProcessing) {
                this.isProcessing = false;
                this.hideTypingIndicator();
                this._clearProcessingTimeout();
                this.renderMessage({
                    role: 'assistant',
                    content: '🔌 La conexión se interrumpió mientras el agente procesaba tu solicitud. Puedes volver a intentarlo.',
                    timestamp: new Date().toISOString()
                });
            }
            this.updateSendButton();
        });
    },

    _processingTimeout: null,

    _startProcessingTimeout(seconds = 120) {
        this._clearProcessingTimeout();
        this._processingTimeout = setTimeout(() => {
            if (this.isProcessing) {
                this.updateTypingStep(`⏳ Sigue procesando… (${seconds}s). Si no responde, usa el botón de cancelar.`);
            }
        }, seconds * 1000);
    },

    _clearProcessingTimeout() {
        if (this._processingTimeout) {
            clearTimeout(this._processingTimeout);
            this._processingTimeout = null;
        }
    },

    /**
     * Send message
     */
    sendMessage() {
        const content = this.inputEl.value.trim();
        if (!content || this.isProcessing) return;

        // Hide welcome message
        this.hideWelcome();

        // Snapshot attachments before they're cleared, so the rendered bubble
        // keeps owning their previewUrls.
        const sentAttachments = this.attachments.slice();

        // Render user message
        this.renderMessage({
            role: 'user',
            content,
            timestamp: new Date().toISOString(),
            attachments: sentAttachments,
        });

        // Clear input
        this.inputEl.value = '';
        Utils.autoResizeTextarea(this.inputEl);
        this.updateSendButton();

        // Split attachments into text (file content) and images (base64).
        const textAtts = this.attachments
            .filter(a => a.kind === 'text')
            .map(({ name, content, size }) => ({ name, content, size }));
        const imageAtts = this.attachments
            .filter(a => a.kind === 'image')
            .map(a => a.base64);
        const imageNames = this.attachments
            .filter(a => a.kind === 'image')
            .map(a => a.name);

        // Send via WebSocket
        const mode = App.state.mode;
        if (mode === 'chat') {
            // Stream chat doesn't carry attachments yet; fall back to non-stream
            // when there's anything attached so files/images aren't dropped.
            if (textAtts.length || imageAtts.length) {
                wsManager.sendChat(content, textAtts, imageAtts, imageNames);
            } else {
                wsManager.sendStreamChat(content);
            }
        } else {
            wsManager.sendChat(content, textAtts, imageAtts, imageNames);
        }

        // Clear attachments
        this.clearAttachments();
    },

    /**
     * Render a message
     */
    renderMessage(msg) {
        const messageEl = document.createElement('div');
        messageEl.className = `message ${msg.role}`;

        const avatar = msg.role === 'user' ? '👤' : '🦙';
        const author = msg.role === 'user' ? 'Tú' : 'Asistente';

        messageEl.innerHTML = `
            <div class="message-avatar">${avatar}</div>
            <div class="message-content">
                <div class="message-header">
                    <span class="message-author">${author}</span>
                    <span class="message-time">${Utils.formatTime(msg.timestamp)}</span>
                </div>
                <div class="message-body" data-raw="${(msg.content || '').replace(/"/g, '&quot;')}">
                    ${Utils.parseMarkdown(msg.content)}
                </div>
            </div>
        `;

        if (msg.role === 'user') {
            const bodyEl = messageEl.querySelector('.message-body');
            bodyEl.title = 'Doble clic para editar y reenviar';
            bodyEl.addEventListener('dblclick', () => this._enterEditMode(bodyEl));
        }

        // Attachments rendered inside the bubble.
        const atts = msg.attachments;
        if (atts && atts.length) {
            const contentEl = messageEl.querySelector('.message-content');
            contentEl.appendChild(this._renderMessageAttachments(atts));
        }

        this.messagesEl.appendChild(messageEl);

        // Syntax highlighting + copy buttons for every code block in this message.
        this._enhanceCodeBlocks(messageEl);

        this.scrollToBottom();
    },

    /**
     * Apply highlight.js and inject copy buttons into every <pre><code> block
     * found inside a rendered message element.
     */
    _enhanceCodeBlocks(messageEl) {
        messageEl.querySelectorAll('pre code').forEach(codeEl => {
            if (window.hljs) hljs.highlightElement(codeEl);

            const pre = codeEl.parentElement;
            if (pre.querySelector('.code-copy-btn')) return; // already done

            const btn = document.createElement('button');
            btn.className = 'code-copy-btn';
            btn.title = 'Copiar código';
            btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2"/>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
            </svg>`;
            btn.addEventListener('click', async () => {
                const text = codeEl.textContent || '';
                try {
                    await navigator.clipboard.writeText(text);
                    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                        stroke="currentColor" stroke-width="2">
                        <polyline points="20 6 9 17 4 12"/>
                    </svg>`;
                    setTimeout(() => {
                        btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                            stroke="currentColor" stroke-width="2">
                            <rect x="9" y="9" width="13" height="13" rx="2"/>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                        </svg>`;
                    }, 1500);
                } catch (_) { /* clipboard access denied */ }
            });
            pre.style.position = 'relative';
            pre.appendChild(btn);
        });
    },

    /**
     * Build an attachments strip for a rendered message.
     * Accepts attachments in two shapes:
     *  - rich (fresh send): { kind, name, previewUrl?, base64? }
     *  - lean (server reload): a string filename, optionally prefixed with 🖼️
     */
    _renderMessageAttachments(atts) {
        const strip = document.createElement('div');
        strip.className = 'message-attachments';

        for (const raw of atts) {
            const att = typeof raw === 'string'
                ? this._parseLeanAttachment(raw)
                : raw;

            const chip = document.createElement('div');
            chip.className = 'message-attachment'
                + (att.kind === 'image' ? ' message-attachment-image' : '');

            if (att.kind === 'image' && (att.previewUrl || att.base64)) {
                const img = document.createElement('img');
                img.src = att.previewUrl
                    || `data:image/png;base64,${att.base64}`;
                img.alt = att.name || '';
                img.className = 'message-attachment-thumb';
                chip.appendChild(img);
            }

            const label = document.createElement('span');
            label.className = 'message-attachment-name';
            label.textContent = (att.kind === 'image' ? '🖼️ ' : '📎 ')
                + (att.name || 'archivo');
            chip.appendChild(label);

            strip.appendChild(chip);
        }
        return strip;
    },

    /**
     * Show RAG file suggestions below the last assistant message.
     * Replaces any previous suggestion strip so they don't pile up.
     */
    _showRagSuggestions(suggestions) {
        // Remove any previous strip
        this.messagesEl.querySelectorAll('.rag-suggestions').forEach(el => el.remove());

        const strip = document.createElement('div');
        strip.className = 'rag-suggestions';

        const label = document.createElement('span');
        label.className = 'rag-suggestions-label';
        label.textContent = '📂 Archivos relevantes:';
        strip.appendChild(label);

        for (const s of suggestions.slice(0, 5)) {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'rag-chip';
            chip.title = s.reason || s.snippet || '';
            chip.textContent = s.path.split('/').pop(); // show only filename
            chip.addEventListener('click', () => {
                // Insert a reference to the file into the input
                const ref = `\`${s.path}\``;
                const input = document.getElementById('message-input');
                if (input) {
                    const pos = input.selectionStart;
                    input.value = input.value.slice(0, pos) + ref + input.value.slice(pos);
                    input.focus();
                    Utils.autoResizeTextarea(input);
                    if (window.Chat) Chat.updateSendButton();
                }
                chip.classList.add('rag-chip-used');
            });
            strip.appendChild(chip);
        }

        this.messagesEl.appendChild(strip);
        this.scrollToBottom();
    },

    _parseLeanAttachment(name) {
        const isImage = /^🖼️/.test(name) || /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(name);
        const cleanName = name.replace(/^🖼️\s*/, '').replace(/^📎\s*/, '');
        return { kind: isImage ? 'image' : 'text', name: cleanName };
    },

    /**
     * Put a user message body into inline edit mode
     */
    _enterEditMode(bodyEl) {
        if (bodyEl.classList.contains('editing') || this.isProcessing) return;
        bodyEl.classList.add('editing');

        const original = bodyEl.dataset.raw || bodyEl.textContent.trim();
        bodyEl.innerHTML = `
            <textarea class="msg-edit-textarea">${original}</textarea>
            <div class="msg-edit-actions">
                <button type="button" class="msg-edit-cancel">Cancelar</button>
                <button type="button" class="msg-edit-send">Reenviar ↵</button>
            </div>
        `;

        const textarea = bodyEl.querySelector('.msg-edit-textarea');
        textarea.style.height = 'auto';
        textarea.style.height = textarea.scrollHeight + 'px';
        textarea.focus();
        textarea.setSelectionRange(textarea.value.length, textarea.value.length);

        textarea.addEventListener('input', () => {
            textarea.style.height = 'auto';
            textarea.style.height = textarea.scrollHeight + 'px';
        });

        textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._submitEdit(bodyEl, textarea.value);
            }
            if (e.key === 'Escape') {
                this._cancelEdit(bodyEl, original);
            }
        });

        bodyEl.querySelector('.msg-edit-cancel').addEventListener('click', () => {
            this._cancelEdit(bodyEl, original);
        });
        bodyEl.querySelector('.msg-edit-send').addEventListener('click', () => {
            this._submitEdit(bodyEl, textarea.value);
        });
    },

    _cancelEdit(bodyEl, original) {
        bodyEl.classList.remove('editing');
        bodyEl.innerHTML = Utils.parseMarkdown(original);
    },

    _submitEdit(bodyEl, newContent) {
        const trimmed = newContent.trim();
        if (!trimmed) return;

        // Restore the bubble with the new text
        bodyEl.classList.remove('editing');
        bodyEl.dataset.raw = trimmed;
        bodyEl.innerHTML = Utils.parseMarkdown(trimmed);

        // Send to model
        this.hideWelcome();
        this._startProcessingTimeout(120);
        const mode = App.state.mode;
        if (mode === 'chat') {
            wsManager.sendStreamChat(trimmed);
        } else {
            wsManager.sendChat(trimmed, []);
        }
    },

    /**
     * Create streaming message placeholder
     */
    createStreamingMessage() {
        const messageEl = document.createElement('div');
        messageEl.className = 'message assistant';
        messageEl.id = 'streaming-message';

        messageEl.innerHTML = `
            <div class="message-avatar">🦙</div>
            <div class="message-content">
                <div class="message-header">
                    <span class="message-author">Asistente</span>
                    <span class="message-time">${Utils.formatTime(new Date())}</span>
                </div>
                <div class="message-body">
                    <span class="streaming-content"></span>
                    <span class="cursor">▊</span>
                </div>
            </div>
        `;

        this.messagesEl.appendChild(messageEl);
        this.scrollToBottom();

        return messageEl;
    },

    /**
     * Append to streaming message
     */
    appendToStreamingMessage(content) {
        if (!this.streamingMessage) return;

        const contentEl = this.streamingMessage.querySelector('.streaming-content');
        if (contentEl) {
            contentEl.textContent += content;
            this.scrollToBottom();
        }
    },

    /**
     * Finalize streaming message
     */
    finalizeStreamingMessage(finalContent) {
        if (!this.streamingMessage) return;

        const bodyEl = this.streamingMessage.querySelector('.message-body');
        if (bodyEl) {
            bodyEl.innerHTML = Utils.parseMarkdown(finalContent);
        }

        this._enhanceCodeBlocks(this.streamingMessage);
        this.streamingMessage = null;
    },

    /**
     * Render tool call result
     */
    renderToolCall(result) {
        const lastMessage = this.messagesEl.querySelector('.message.assistant:last-child');
        if (!lastMessage) return;

        const bodyEl = lastMessage.querySelector('.message-body');
        if (!bodyEl) return;

        const toolEl = document.createElement('div');
        toolEl.className = `tool-call ${result.success ? '' : 'error'}`;
        toolEl.innerHTML = `
            <div class="tool-call-header" onclick="this.parentElement.classList.toggle('expanded')">
                <span class="tool-call-name">
                    🔧 ${result.tool_call.tool}
                </span>
                <span class="tool-call-status ${result.success ? 'success' : 'error'}">
                    ${result.success ? '✓ OK' : '✗ Error'}
                </span>
            </div>
            <div class="tool-call-body">
                <pre>${Utils.escapeHtml(result.output || result.error || '')}</pre>
            </div>
        `;

        bodyEl.appendChild(toolEl);
    },

    /**
     * Update typing indicator text with current agent step
     */
    updateTypingStep(message) {
        const indicator = document.getElementById('typing-indicator');
        if (!indicator) return;
        const span = indicator.querySelector('span');
        if (span) {
            span.textContent = message;
        }
    },

    /**
     * Show typing indicator with cancel button
     */
    showTypingIndicator() {
        const existing = document.getElementById('typing-indicator');
        if (existing) return;

        const indicator = document.createElement('div');
        indicator.id = 'typing-indicator';
        indicator.className = 'message assistant';
        indicator.innerHTML = `
            <div class="message-avatar">🦙</div>
            <div class="typing-indicator">
                <div class="typing-dots">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
                <span>Pensando...</span>
                <button
                    style="margin-left:12px;padding:2px 10px;font-size:0.8em;
                           border:1px solid #888;border-radius:4px;cursor:pointer;
                           background:transparent;color:inherit;opacity:0.75"
                    onclick="wsManager.sendCancel()"
                    title="Cancelar ejecución">
                    ✕ Cancelar
                </button>
            </div>
        `;

        this.messagesEl.appendChild(indicator);
        this.scrollToBottom();
    },

    /**
     * Hide typing indicator
     */
    hideTypingIndicator() {
        const indicator = document.getElementById('typing-indicator');
        if (indicator) {
            indicator.remove();
        }
    },

    /**
     * Show approval modal
     */
    showApprovalModal(pending) {
        const modal = document.getElementById('approval-modal');
        const details = document.getElementById('approval-details');
        
        details.innerHTML = `
            <p><strong>Acción:</strong></p>
            <pre>${Utils.escapeHtml(pending.tool_call)}</pre>
            <p>${Utils.escapeHtml(pending.description)}</p>
        `;

        modal.style.display = 'flex';

        document.getElementById('approve-action').onclick = () => {
            wsManager.sendApproval(true);
            modal.style.display = 'none';
        };

        document.getElementById('reject-action').onclick = () => {
            wsManager.sendApproval(false);
            modal.style.display = 'none';
        };

        modal.querySelector('.modal-backdrop').onclick = () => {
            modal.style.display = 'none';
        };
    },

    /**
     * Returns true if the active model declares vision support.
     */
    modelSupportsVision() {
        const model = App.state.model;
        const caps = (App.state.modelCapabilities || {})[model] || [];
        return caps.includes('vision');
    },

    /**
     * Handle file selection (from picker, drag-drop or clipboard).
     */
    async handleFileSelect(files) {
        for (const file of files) {
            await this.addFileAttachment(file);
        }
    },

    /**
     * Read a single File/Blob and push it into `this.attachments`,
     * splitting between image (base64) and text (utf-8) flavours.
     */
    async addFileAttachment(file) {
        if (file.size > 10 * 1024 * 1024) {
            Utils.showToast(`Archivo demasiado grande (max 10MB): ${file.name || 'sin nombre'}`, 'error');
            return;
        }

        const isImage = (file.type || '').startsWith('image/');
        const name = file.name || (isImage
            ? `screenshot-${Date.now()}.${(file.type.split('/')[1] || 'png').replace('jpeg', 'jpg')}`
            : `file-${Date.now()}`);

        try {
            if (isImage) {
                if (!this.modelSupportsVision()) {
                    Utils.showToast(
                        `El modelo actual no soporta imágenes. ${name} se ignoró.`,
                        'info'
                    );
                    return;
                }
                const base64 = await Utils.readFileAsBase64(file);
                const att = {
                    kind: 'image',
                    name,
                    base64,
                    size: file.size,
                    previewUrl: URL.createObjectURL(file)
                };
                this.attachments.push(att);
                this.renderAttachment(att);
            } else {
                const content = await Utils.readFileAsText(file);
                const att = {
                    kind: 'text',
                    name,
                    content,
                    size: file.size
                };
                this.attachments.push(att);
                this.renderAttachment(att);
            }
        } catch (error) {
            Utils.showToast(`Error al leer ${name}`, 'error');
        }
    },

    /**
     * Capture pasted images / files from the clipboard.
     * Lets plain text paste through untouched so the textarea behaves normally.
     */
    async handlePaste(event) {
        const cd = event.clipboardData;
        if (!cd) return;

        const items = Array.from(cd.items || []);
        const files = [];

        // `items` is the richest source: it covers screenshots that arrive as
        // `image/png` blobs without ever appearing in `files`.
        for (const item of items) {
            if (item.kind === 'file') {
                const f = item.getAsFile();
                if (f) files.push(f);
            }
        }
        // Fallback / drag-drop style sources expose `files` directly.
        if (files.length === 0 && cd.files && cd.files.length) {
            for (const f of cd.files) files.push(f);
        }

        if (files.length === 0) return;  // pure text paste — let the browser handle it

        // We're handling at least one file: prevent the binary noise (e.g. base64
        // image data) from also being inserted as text into the textarea.
        event.preventDefault();
        for (const f of files) {
            await this.addFileAttachment(f);
        }
    },

    /**
     * Render attachment preview
     */
    renderAttachment(att) {
        const item = document.createElement('div');
        item.className = 'attachment-item' + (att.kind === 'image' ? ' attachment-image' : '');

        if (att.kind === 'image') {
            const img = document.createElement('img');
            img.src = att.previewUrl;
            img.alt = att.name;
            img.className = 'attachment-thumb';
            item.appendChild(img);
        }

        const label = document.createElement('span');
        label.textContent = (att.kind === 'image' ? '🖼️ ' : '📎 ') + att.name;
        item.appendChild(label);

        const removeBtn = document.createElement('button');
        removeBtn.className = 'attachment-remove';
        removeBtn.textContent = '×';
        removeBtn.onclick = () => {
            if (att.previewUrl) URL.revokeObjectURL(att.previewUrl);
            this.attachments = this.attachments.filter(a => a !== att);
            item.remove();
        };
        item.appendChild(removeBtn);

        this.attachmentsPreview.appendChild(item);
    },

    /**
     * Clear attachments staging area (does NOT revoke previewUrls — the
     * caller is expected to have transferred ownership to a rendered bubble).
     */
    clearAttachments() {
        this.attachments = [];
        this.attachmentsPreview.innerHTML = '';
    },

    /**
     * Restore messages from a historical session (read-only view).
     */
    restoreMessages(messages, meta = {}) {
        // Clear current display + any previous history banner
        this.messagesEl.querySelectorAll('.message, .history-view-banner').forEach(el => el.remove());
        this.hideWelcome();

        if (!messages || messages.length === 0) {
            this.showWelcome();
            return;
        }

        messages.forEach(msg => this.renderMessage(msg));
        this.scrollToBottom();

        // Optionally show banner indicating this is a historical view
        const banner = document.createElement('div');
        banner.className = 'history-view-banner';
        banner.innerHTML = `
            <span>Vista del historial${meta.title ? ': <em>' + Utils.escapeHtml(meta.title) + '</em>' : ''}</span>
            <button id="history-resume-btn">Continuar esta conversación</button>
        `;
        this.messagesEl.insertBefore(banner, this.messagesEl.firstChild);

        document.getElementById('history-resume-btn')?.addEventListener('click', async () => {
            banner.remove();
            // Reconnect using the historical session id
            if (meta.sessionId && window.wsManager) {
                wsManager.disconnect();
                await wsManager.connect(meta.sessionId);
                if (window.Sidebar) Sidebar.onConnected();
            }
        });
    },

    /**
     * Clear chat
     */
    clearChat() {
        // Clear messages and any history banner
        this.messagesEl.querySelectorAll('.message, .history-view-banner').forEach(el => el.remove());
        
        // Show welcome
        this.showWelcome();
        
        // Clear on server
        fetch(`/api/sessions/${wsManager.sessionId}/messages`, {
            method: 'DELETE'
        });
    },

    /**
     * Hide welcome message
     */
    hideWelcome() {
        if (this.welcomeMessage) {
            this.welcomeMessage.style.display = 'none';
        }
    },

    /**
     * Show welcome message
     */
    showWelcome() {
        if (this.welcomeMessage) {
            this.welcomeMessage.style.display = 'flex';
        }
    },

    /**
     * Scroll to bottom of messages
     */
    scrollToBottom() {
        Utils.scrollToBottom(this.messagesContainer);
    },

    /**
     * Update send button state
     */
    updateSendButton() {
        const hasContent = this.inputEl.value.trim().length > 0;
        const isConnected = wsManager && wsManager.isConnected;
        this.sendBtn.disabled = !hasContent || this.isProcessing || !isConnected;
    },

};

// Make available globally
window.Chat = Chat;
