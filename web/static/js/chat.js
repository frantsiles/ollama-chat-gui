
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

            if (data.tool_results && data.tool_results.length > 0) {
                data.tool_results.forEach(result => {
                    this.renderToolCall(result);
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
            this.showApprovalModal(data.pending);
        });

        wsManager.on('plan_created', (data) => {
            this.isProcessing = false;
            this.hideTypingIndicator();
            Plan.showPlan(data.plan);
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

        // Render user message
        this.renderMessage({
            role: 'user',
            content,
            timestamp: new Date().toISOString()
        });

        // Clear input
        this.inputEl.value = '';
        Utils.autoResizeTextarea(this.inputEl);
        this.updateSendButton();

        // Send via WebSocket
        const mode = App.state.mode;
        if (mode === 'chat') {
            wsManager.sendStreamChat(content);
        } else {
            wsManager.sendChat(content, this.attachments);
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
                <div class="message-body">
                    ${Utils.parseMarkdown(msg.content)}
                </div>
            </div>
        `;

        this.messagesEl.appendChild(messageEl);
        this.scrollToBottom();
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
     * Handle file selection
     */
    async handleFileSelect(files) {
        for (const file of files) {
            if (file.size > 10 * 1024 * 1024) {
                Utils.showToast('Archivo demasiado grande (max 10MB)', 'error');
                continue;
            }

            try {
                const content = await Utils.readFileAsText(file);
                this.attachments.push({
                    name: file.name,
                    content,
                    size: file.size
                });
                this.renderAttachment(file.name);
            } catch (error) {
                Utils.showToast(`Error al leer ${file.name}`, 'error');
            }
        }
    },

    /**
     * Render attachment preview
     */
    renderAttachment(name) {
        const item = document.createElement('div');
        item.className = 'attachment-item';
        item.innerHTML = `
            <span>📎 ${name}</span>
            <button class="attachment-remove" data-name="${name}">×</button>
        `;

        item.querySelector('.attachment-remove').onclick = () => {
            this.attachments = this.attachments.filter(a => a.name !== name);
            item.remove();
        };

        this.attachmentsPreview.appendChild(item);
    },

    /**
     * Clear attachments
     */
    clearAttachments() {
        this.attachments = [];
        this.attachmentsPreview.innerHTML = '';
    },

    /**
     * Clear chat
     */
    clearChat() {
        // Clear messages except welcome
        const messages = this.messagesEl.querySelectorAll('.message');
        messages.forEach(msg => msg.remove());
        
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
