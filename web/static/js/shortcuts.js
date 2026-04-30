
/**
 * Keyboard Shortcuts module.
 *
 * Global shortcuts (document-level):
 *   Ctrl+Enter          → Send message
 *   Escape              → Cancel generation / close open modals
 *   Ctrl+Shift+H        → Toggle Historial panel
 *   Ctrl+Shift+S        → Toggle Skills panel
 *   Ctrl+Shift+F        → Toggle Search panel
 *   Ctrl+Shift+E        → Toggle Explorer panel
 *   Ctrl+L              → Focus message input
 *
 * Textarea-local shortcuts (handled in chat.js):
 *   ↑  (empty input)    → Recover last sent message
 *   ↓  (at recalled)   → Clear recovered message
 */

const Shortcuts = {
    _messageHistory: [],   // messages sent this session, oldest→newest
    _historyIdx: -1,       // current position when navigating with ↑/↓
    _draft: '',            // saved draft while navigating history

    init() {
        document.addEventListener('keydown', (e) => this._onGlobal(e));
    },

    // -------------------------------------------------------------------------
    // Global handler
    // -------------------------------------------------------------------------

    _onGlobal(e) {
        const tag = document.activeElement?.tagName;
        const inInput = tag === 'INPUT' || tag === 'TEXTAREA' || document.activeElement?.isContentEditable;

        // Ctrl+Enter — send message (works from anywhere, including textarea)
        if (e.ctrlKey && e.key === 'Enter') {
            e.preventDefault();
            if (window.Chat && !Chat.isProcessing) Chat.sendMessage();
            return;
        }

        // Escape — cancel generation OR close open modals
        if (e.key === 'Escape' && !e.ctrlKey && !e.shiftKey) {
            // Don't intercept if user is editing a text field (let browser handle)
            if (inInput && document.activeElement?.id !== 'message-input') return;

            if (window.Chat?.isProcessing) {
                e.preventDefault();
                wsManager.sendCancel();
                return;
            }
            // Close skills modal if open
            const skillsModal = document.querySelector('.skills-modal-overlay:not([style*="display: none"])');
            if (skillsModal) { e.preventDefault(); skillsModal.style.display = 'none'; return; }
            return;
        }

        // Panel shortcuts — only when not typing in an input/textarea
        if (e.ctrlKey && e.shiftKey && !inInput) {
            switch (e.key.toUpperCase()) {
                case 'H':
                    e.preventDefault();
                    this._togglePanel('history');
                    return;
                case 'S':
                    e.preventDefault();
                    this._togglePanel('config');
                    return;
                case 'F':
                    e.preventDefault();
                    this._togglePanel('search');
                    return;
                case 'E':
                    e.preventDefault();
                    this._togglePanel('explorer');
                    return;
            }
        }

        // Ctrl+L — focus message input (like browser address bar pattern)
        if (e.ctrlKey && e.key === 'l' && !e.shiftKey && !inInput) {
            e.preventDefault();
            document.getElementById('message-input')?.focus();
            return;
        }
    },

    // -------------------------------------------------------------------------
    // Panel toggle helper
    // -------------------------------------------------------------------------

    _togglePanel(name) {
        if (!window.Explorer) return;
        const panel = document.getElementById('side-panel');
        const isCollapsed = panel?.classList.contains('collapsed');
        const currentPanel = document.querySelector('.panel.active')?.dataset?.panel;

        if (isCollapsed || currentPanel !== name) {
            Explorer.setPanel(name);
            Explorer._expandSidePanel();
        } else {
            Explorer._collapseSidePanel();
        }
    },

    // -------------------------------------------------------------------------
    // Message history navigation (called from chat.js textarea keydown)
    // -------------------------------------------------------------------------

    /** Record a sent message for ↑/↓ recall. */
    recordMessage(text) {
        if (!text.trim()) return;
        // Avoid consecutive duplicates
        if (this._messageHistory[this._messageHistory.length - 1] === text) return;
        this._messageHistory.push(text);
        // Keep last 50 messages
        if (this._messageHistory.length > 50) this._messageHistory.shift();
        this._historyIdx = -1;
    },

    /**
     * Handle ↑/↓ inside the textarea.
     * Returns true if the event was consumed.
     */
    handleTextareaKey(e, inputEl) {
        if (e.key === 'ArrowUp') {
            if (inputEl.value !== '' && this._historyIdx === -1) return false;
            if (this._messageHistory.length === 0) return false;

            // Save draft on first press
            if (this._historyIdx === -1) this._draft = inputEl.value;

            const nextIdx = this._historyIdx === -1
                ? this._messageHistory.length - 1
                : Math.max(0, this._historyIdx - 1);

            if (nextIdx === this._historyIdx) return true; // already at oldest
            this._historyIdx = nextIdx;
            inputEl.value = this._messageHistory[this._historyIdx];
            inputEl.dispatchEvent(new Event('input'));
            // Move cursor to end
            inputEl.selectionStart = inputEl.selectionEnd = inputEl.value.length;
            return true;
        }

        if (e.key === 'ArrowDown' && this._historyIdx !== -1) {
            const nextIdx = this._historyIdx + 1;
            if (nextIdx >= this._messageHistory.length) {
                // Back to draft
                this._historyIdx = -1;
                inputEl.value = this._draft;
                inputEl.dispatchEvent(new Event('input'));
            } else {
                this._historyIdx = nextIdx;
                inputEl.value = this._messageHistory[this._historyIdx];
                inputEl.dispatchEvent(new Event('input'));
            }
            inputEl.selectionStart = inputEl.selectionEnd = inputEl.value.length;
            return true;
        }

        // Any other key while navigating resets history index
        if (this._historyIdx !== -1 && e.key !== 'ArrowUp' && e.key !== 'ArrowDown') {
            this._historyIdx = -1;
            this._draft = '';
        }

        return false;
    },
};

window.Shortcuts = Shortcuts;
