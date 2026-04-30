
/**
 * History module — panel de conversaciones guardadas.
 * Funcionalidades: listar, buscar, editar título, exportar, importar, limpiar.
 */

const History = {
    _conversations: [],
    _searchEl: null,
    _listEl: null,
    _emptyEl: null,
    _importInput: null,

    init() {
        this._searchEl  = document.getElementById('history-search');
        this._listEl    = document.getElementById('history-list');
        this._emptyEl   = document.getElementById('history-empty');
        this._importInput = document.getElementById('history-import-input');

        if (!this._listEl) return;
        this._bindEvents();
    },

    _bindEvents() {
        if (this._searchEl) {
            this._searchEl.addEventListener('input', () => this._render());
        }

        document.getElementById('history-new-btn')
            ?.addEventListener('click', () => this._newConversation());

        document.getElementById('history-refresh-btn')
            ?.addEventListener('click', () => this.load());

        document.getElementById('history-clear-all-btn')
            ?.addEventListener('click', () => this._clearAll());

        document.getElementById('history-export-all-btn')
            ?.addEventListener('click', () => this._exportAll());

        document.getElementById('history-import-btn')
            ?.addEventListener('click', () => this._importInput?.click());

        this._importInput?.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) this._importFile(file);
            e.target.value = '';
        });
    },

    // -------------------------------------------------------------------------
    // Load & Render
    // -------------------------------------------------------------------------

    async load() {
        try {
            const res = await fetch('/api/conversations');
            if (!res.ok) return;
            const data = await res.json();
            this._conversations = data.conversations || [];
            this._render();
        } catch (e) {
            Utils.log('HISTORY', 'Error loading conversations:', e);
        }
    },

    _render() {
        if (!this._listEl) return;
        const query = (this._searchEl?.value || '').toLowerCase();
        const filtered = query
            ? this._conversations.filter(c =>
                (c.title || '').toLowerCase().includes(query) ||
                (c.model || '').toLowerCase().includes(query)
              )
            : this._conversations;

        this._listEl.innerHTML = '';

        if (filtered.length === 0) {
            if (this._emptyEl) this._emptyEl.style.display = '';
            return;
        }
        if (this._emptyEl) this._emptyEl.style.display = 'none';

        const currentId = wsManager?.sessionId;
        filtered.forEach(conv => this._renderItem(conv, currentId));
    },

    _renderItem(conv, currentId) {
        const el = document.createElement('div');
        el.className = 'history-item' + (conv.id === currentId ? ' active' : '');
        el.dataset.id = conv.id;

        const title = conv.title || 'Sin título';
        const date  = this._formatDate(conv.updated_at || conv.created_at);
        const count = conv.message_count || 0;
        const model = conv.model
            ? `<span class="history-model">${Utils.escapeHtml(conv.model)}</span>`
            : '';

        el.innerHTML = `
            <div class="history-item-body">
                <div class="history-title-row">
                    <span class="history-title" title="${Utils.escapeHtml(title)}">${Utils.escapeHtml(title)}</span>
                </div>
                <div class="history-meta">${date} · ${count} msg ${model}</div>
            </div>
            <div class="history-item-actions">
                <button type="button" class="history-edit-btn" title="Editar título">
                    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
                        <path d="M11.5 2.5a1.41 1.41 0 0 1 2 2L5 13H3v-2L11.5 2.5z"/>
                    </svg>
                </button>
                <button type="button" class="history-action-btn history-export-btn" title="Exportar conversación">
                    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
                        <path d="M8 2v8M5 7l3 3 3-3M3 12h10"/>
                    </svg>
                </button>
                <button type="button" class="history-action-btn history-del-btn" title="Eliminar">
                    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
                        <path d="M2 4h12M5 4V2h6v2M6 7v5M10 7v5M3 4l1 9h8l1-9"/>
                    </svg>
                </button>
            </div>
        `;

        el.querySelector('.history-item-body').addEventListener('click', () => this._load(conv.id));
        el.querySelector('.history-edit-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            this._startTitleEdit(el, conv);
        });
        el.querySelector('.history-export-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            this._exportOne(conv.id, conv.title);
        });
        el.querySelector('.history-del-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            this._delete(conv.id);
        });

        this._listEl.appendChild(el);
    },

    // -------------------------------------------------------------------------
    // Load (view) a historical conversation
    // -------------------------------------------------------------------------

    async _load(sessionId) {
        try {
            const res = await fetch(`/api/conversations/${sessionId}/messages`);
            if (!res.ok) { Utils.showToast('No se pudo cargar la conversación', 'error'); return; }
            const data = await res.json();

            if (window.Chat && typeof Chat.restoreMessages === 'function') {
                Chat.restoreMessages(data.messages, {
                    sessionId,
                    title: data.title,
                    model: data.model,
                    mode: data.mode,
                });
            }

            this._listEl.querySelectorAll('.history-item').forEach(el =>
                el.classList.toggle('active', el.dataset.id === sessionId)
            );
        } catch (e) {
            Utils.showToast('Error cargando conversación', 'error');
        }
    },

    // -------------------------------------------------------------------------
    // Inline title edit
    // -------------------------------------------------------------------------

    _startTitleEdit(itemEl, conv) {
        const titleSpan = itemEl.querySelector('.history-title');
        const currentTitle = conv.title || '';

        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'history-title-input';
        input.value = currentTitle;
        input.maxLength = 120;

        titleSpan.replaceWith(input);
        input.focus();
        input.select();

        const commit = async () => {
            const newTitle = input.value.trim();
            if (newTitle && newTitle !== currentTitle) {
                await this._saveTitle(conv.id, newTitle);
                conv.title = newTitle;
            }
            // Restaurar span con título actualizado
            const span = document.createElement('span');
            span.className = 'history-title';
            span.title = conv.title || currentTitle;
            span.textContent = conv.title || currentTitle;
            input.replaceWith(span);
            span.parentElement?.querySelector('.history-edit-btn')?.focus();
        };

        input.addEventListener('blur', commit);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); commit(); }
            if (e.key === 'Escape') {
                conv.title = currentTitle; // revert
                const span = document.createElement('span');
                span.className = 'history-title';
                span.title = currentTitle;
                span.textContent = currentTitle;
                input.removeEventListener('blur', commit);
                input.replaceWith(span);
            }
        });
    },

    async _saveTitle(sessionId, title) {
        try {
            await fetch(`/api/conversations/${sessionId}/title`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title }),
            });
        } catch (e) {
            Utils.showToast('Error guardando título', 'error');
        }
    },

    // -------------------------------------------------------------------------
    // Delete
    // -------------------------------------------------------------------------

    async _delete(sessionId) {
        try {
            const res = await fetch(`/api/conversations/${sessionId}`, { method: 'DELETE' });
            if (!res.ok) { Utils.showToast('No se pudo eliminar', 'error'); return; }
            this._conversations = this._conversations.filter(c => c.id !== sessionId);
            this._render();
            Utils.showToast('Conversación eliminada', 'success');
        } catch (e) {
            Utils.showToast('Error eliminando conversación', 'error');
        }
    },

    async _clearAll() {
        if (!confirm('¿Eliminar TODAS las conversaciones del historial? Esta acción no se puede deshacer.')) return;
        try {
            const res = await fetch('/api/conversations', { method: 'DELETE' });
            if (!res.ok) { Utils.showToast('Error al limpiar historial', 'error'); return; }
            const data = await res.json();
            this._conversations = [];
            this._render();
            Utils.showToast(`Historial limpiado (${data.deleted} conversaciones)`, 'success');
        } catch (e) {
            Utils.showToast('Error al limpiar historial', 'error');
        }
    },

    // -------------------------------------------------------------------------
    // New conversation
    // -------------------------------------------------------------------------

    async _newConversation() {
        if (window.Chat && typeof Chat.clearChat === 'function') Chat.clearChat();
        if (window.wsManager) {
            wsManager.disconnect();
            await wsManager.connect();
            if (window.Sidebar) Sidebar.onConnected();
        }
        Utils.showToast('Nueva conversación iniciada', 'success');
    },

    // -------------------------------------------------------------------------
    // Export
    // -------------------------------------------------------------------------

    async _exportOne(sessionId, title) {
        try {
            const res = await fetch(`/api/conversations/${sessionId}/export`);
            if (!res.ok) { Utils.showToast('Error al exportar', 'error'); return; }
            const data = await res.json();
            const filename = this._safeFilename(title || sessionId) + '.json';
            this._downloadJSON(data, filename);
        } catch (e) {
            Utils.showToast('Error al exportar', 'error');
        }
    },

    async _exportAll() {
        try {
            const res = await fetch('/api/conversations/export-all');
            if (!res.ok) { Utils.showToast('Error al exportar todo', 'error'); return; }
            const data = await res.json();
            const date = new Date().toISOString().slice(0, 10);
            this._downloadJSON(data, `ollama-chat-historial-${date}.json`);
        } catch (e) {
            Utils.showToast('Error al exportar todo', 'error');
        }
    },

    _downloadJSON(data, filename) {
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    },

    // -------------------------------------------------------------------------
    // Import
    // -------------------------------------------------------------------------

    async _importFile(file) {
        try {
            const text = await file.text();
            const payload = JSON.parse(text);
            const res = await fetch('/api/conversations/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                Utils.showToast(err.detail || 'Error al importar', 'error');
                return;
            }
            const data = await res.json();
            Utils.showToast(`${data.count} conversación(es) importada(s)`, 'success');
            await this.load();
        } catch (e) {
            Utils.showToast('El archivo no es un JSON válido', 'error');
        }
    },

    // -------------------------------------------------------------------------
    // Live update from chat
    // -------------------------------------------------------------------------

    onSessionSaved(sessionData) {
        if (!sessionData?.id) return;
        const idx = this._conversations.findIndex(c => c.id === sessionData.id);
        const entry = {
            id: sessionData.id,
            title: sessionData.title || '',
            model: sessionData.model || '',
            mode: sessionData.mode || 'agent',
            message_count: sessionData.message_count || 0,
            updated_at: new Date().toISOString(),
            created_at: sessionData.created_at || new Date().toISOString(),
        };
        if (idx >= 0) {
            this._conversations[idx] = entry;
        } else {
            this._conversations.unshift(entry);
        }
        this._render();
    },

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    _formatDate(iso) {
        if (!iso) return '';
        try {
            const d = new Date(iso);
            const now = new Date();
            const diffDays = Math.floor((now - d) / 86400000);
            if (diffDays === 0) return 'Hoy ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            if (diffDays === 1) return 'Ayer';
            if (diffDays < 7) return `Hace ${diffDays} días`;
            return d.toLocaleDateString();
        } catch { return ''; }
    },

    _safeFilename(str) {
        return str.replace(/[^a-zA-Z0-9_\-áéíóúüñÁÉÍÓÚÜÑ ]/g, '_').slice(0, 60).trim();
    },
};

window.History = History;
