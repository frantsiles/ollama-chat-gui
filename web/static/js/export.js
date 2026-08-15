/**
 * Export module — exporta el chat activo a Markdown (.md) o PDF (impresión).
 */

const Export = {
    _btn: null,
    _menu: null,

    init() {
        this._btn = document.getElementById('export-btn');
        this._menu = document.getElementById('export-menu');
        if (!this._btn || !this._menu) return;

        this._btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = this._menu.classList.contains('open');
            document.querySelectorAll('.input-selector-menu.open').forEach(m => m.classList.remove('open'));
            document.querySelectorAll('[aria-expanded="true"]').forEach(b => b.setAttribute('aria-expanded', 'false'));
            if (!isOpen) {
                this._menu.classList.add('open');
                this._btn.setAttribute('aria-expanded', 'true');
            }
        });

        this._menu.querySelectorAll('.selector-menu-item').forEach(item => {
            item.addEventListener('click', () => {
                this._menu.classList.remove('open');
                this._btn.setAttribute('aria-expanded', 'false');
                if (item.dataset.format === 'md') this.exportMarkdown();
                else if (item.dataset.format === 'pdf') this.exportPDF();
            });
        });
    },

    _hasMessages() {
        return !!(window.Chat && Chat.messagesEl && Chat.messagesEl.querySelector('.message'));
    },

    _sessionId() {
        return window.wsManager ? wsManager.sessionId : null;
    },

    async exportMarkdown() {
        const sessionId = this._sessionId();
        if (!sessionId || !this._hasMessages()) {
            Utils.showToast('No hay mensajes para exportar', 'error');
            return;
        }
        try {
            const res = await fetch(`/api/conversations/${sessionId}/export?format=md`);
            if (!res.ok) { Utils.showToast('Error al exportar', 'error'); return; }
            const text = await res.text();
            const filename = this._filenameFromHeader(res) || `chat-${sessionId.slice(0, 8)}.md`;
            Utils.downloadText(text, filename, 'text/markdown');
        } catch (e) {
            Utils.showToast('Error al exportar', 'error');
        }
    },

    _filenameFromHeader(res) {
        const disposition = res.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename="?([^"]+)"?/);
        return match ? match[1] : null;
    },

    async exportPDF() {
        const sessionId = this._sessionId();
        if (!sessionId || !this._hasMessages()) {
            Utils.showToast('No hay mensajes para exportar', 'error');
            return;
        }
        await this._injectPrintHeader(sessionId);
        window.print();
    },

    async _injectPrintHeader(sessionId) {
        const container = document.getElementById('messages-container');
        if (!container) return;

        document.getElementById('print-header')?.remove();

        let title = 'Chat';
        let model = '';
        let mode = '';
        let createdAt = '';
        try {
            const res = await fetch(`/api/sessions/${sessionId}`);
            if (res.ok) {
                const data = await res.json();
                const s = data.session || {};
                title = s.title || title;
                model = s.model || '';
                mode = s.mode || '';
                createdAt = s.created_at || '';
            }
        } catch (e) {
            // Cabecera best-effort: si falla, se imprime igual sin metadatos.
        }

        const header = document.createElement('div');
        header.id = 'print-header';
        header.className = 'print-only';
        header.innerHTML = `
            <h1>${Utils.escapeHtml(title)}</h1>
            <p>
                ${model ? `Modelo: ${Utils.escapeHtml(model)} · ` : ''}${mode ? `Modo: ${Utils.escapeHtml(mode)} · ` : ''}${createdAt ? `Creado: ${Utils.escapeHtml(createdAt)}` : ''}
            </p>
        `;
        container.insertBefore(header, container.firstChild);

        window.addEventListener('afterprint', () => {
            document.getElementById('print-header')?.remove();
        }, { once: true });
    },
};

window.Export = Export;
