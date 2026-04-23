
/**
 * MCP Manager UI module
 */

const MCP = {
    servers: [],
    isOpen: false,
    formOpen: false,

    /** Open modal */
    open() {
        document.getElementById('mcp-modal').style.display = 'flex';
        this.isOpen = true;
        this.refresh();
    },

    /** Close modal */
    close() {
        document.getElementById('mcp-modal').style.display = 'none';
        this.isOpen = false;
    },

    /** Initialize module */
    init() {
        this._buildModal();
        this._buildHeaderBtn();
        this._bindEvents();
    },

    /** Build the modal HTML and inject into body */
    _buildModal() {
        const modal = document.createElement('div');
        modal.id = 'mcp-modal';
        modal.className = 'mcp-modal';
        modal.style.display = 'none';
        modal.innerHTML = `
            <div class="mcp-modal-backdrop" id="mcp-backdrop"></div>
            <div class="mcp-modal-content">
                <div class="mcp-modal-header">
                    <h2>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
                            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
                        </svg>
                        MCP Servers
                    </h2>
                    <div class="mcp-header-actions">
                        <button class="btn btn-secondary btn-sm" id="mcp-connect-all">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="13 2 13 9 20 9"/><path d="M11 2H4a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-7"/>
                            </svg>
                            Conectar todos
                        </button>
                        <button class="icon-btn" id="mcp-close">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M18 6L6 18M6 6l12 12"/>
                            </svg>
                        </button>
                    </div>
                </div>
                <div class="mcp-modal-body" id="mcp-modal-body">
                    <div class="mcp-status-bar" id="mcp-status-bar">
                        Verificando disponibilidad MCP...
                    </div>

                    <!-- Add server form (collapsible) -->
                    <div class="mcp-add-form" id="mcp-add-form">
                        <div class="mcp-add-form-header" id="mcp-add-toggle">
                            <span>
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px">
                                    <path d="M12 5v14M5 12h14"/>
                                </svg>
                                Agregar servidor
                            </span>
                            <svg class="mcp-card-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="6 9 12 15 18 9"/>
                            </svg>
                        </div>
                        <div class="mcp-add-form-body" id="mcp-add-form-body">
                            <div class="mcp-form-row">
                                <div class="mcp-field">
                                    <label>Nombre *</label>
                                    <input type="text" id="mcp-new-name" placeholder="filesystem" />
                                </div>
                                <div class="mcp-field">
                                    <label>Tipo</label>
                                    <select id="mcp-new-type">
                                        <option value="stdio">stdio (proceso local)</option>
                                        <option value="sse">SSE (HTTP)</option>
                                    </select>
                                </div>
                            </div>

                            <div id="mcp-stdio-fields" class="mcp-stdio-fields">
                                <div class="mcp-field">
                                    <label>Comando *</label>
                                    <input type="text" id="mcp-new-command" placeholder="npx" />
                                </div>
                                <div class="mcp-field">
                                    <label>Argumentos</label>
                                    <input type="text" id="mcp-new-args" placeholder="-y, @modelcontextprotocol/server-filesystem, /home" />
                                    <span class="mcp-field-hint">Separados por coma</span>
                                </div>
                                <div class="mcp-field">
                                    <label>Variables de entorno</label>
                                    <textarea id="mcp-new-env" placeholder="API_KEY=abc123&#10;DEBUG=true"></textarea>
                                    <span class="mcp-field-hint">Una por línea: CLAVE=VALOR</span>
                                </div>
                            </div>

                            <div id="mcp-sse-fields" class="mcp-sse-fields" style="display:none">
                                <div class="mcp-field">
                                    <label>URL *</label>
                                    <input type="text" id="mcp-new-url" placeholder="http://localhost:3001/sse" />
                                </div>
                            </div>

                            <div class="mcp-field">
                                <label>Descripción</label>
                                <input type="text" id="mcp-new-description" placeholder="Acceso al sistema de archivos" />
                            </div>

                            <div class="mcp-form-actions">
                                <button class="btn btn-secondary btn-sm" id="mcp-form-cancel">Cancelar</button>
                                <button class="btn btn-primary btn-sm" id="mcp-form-save">
                                    Agregar servidor
                                </button>
                            </div>
                        </div>
                    </div>

                    <!-- Server list -->
                    <div class="mcp-server-list" id="mcp-server-list">
                        <div class="mcp-empty">Cargando servidores...</div>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
    },

    /** Add MCP button to header */
    _buildHeaderBtn() {
        const headerRight = document.querySelector('.header-right');
        if (!headerRight) return;

        const btn = document.createElement('button');
        btn.id = 'mcp-open-btn';
        btn.className = 'icon-btn mcp-open-btn';
        btn.setAttribute('aria-label', 'MCP Servers');
        btn.title = 'Gestionar servidores MCP';
        btn.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
            </svg>
        `;
        btn.addEventListener('click', () => this.open());
        // Insert before theme toggle
        const themeBtn = document.getElementById('theme-toggle');
        headerRight.insertBefore(btn, themeBtn);
    },

    /** Bind static events */
    _bindEvents() {
        document.addEventListener('click', (e) => {
            if (e.target.id === 'mcp-backdrop') this.close();
            if (e.target.closest('#mcp-close')) this.close();
        });

        document.getElementById('mcp-connect-all').addEventListener('click', () => this._connectAll());
        document.getElementById('mcp-add-toggle').addEventListener('click', () => this._toggleAddForm());
        document.getElementById('mcp-form-cancel').addEventListener('click', () => this._closeAddForm());
        document.getElementById('mcp-form-save').addEventListener('click', () => this._submitAdd());
        document.getElementById('mcp-new-type').addEventListener('change', (e) => this._onTypeChange(e.target.value));
    },

    /** Toggle add form */
    _toggleAddForm() {
        const body = document.getElementById('mcp-add-form-body');
        const chevron = document.querySelector('#mcp-add-toggle .mcp-card-chevron');
        const open = body.classList.toggle('open');
        chevron.classList.toggle('open', open);
        if (open) this._resetForm();
    },

    _closeAddForm() {
        const body = document.getElementById('mcp-add-form-body');
        const chevron = document.querySelector('#mcp-add-toggle .mcp-card-chevron');
        body.classList.remove('open');
        chevron.classList.remove('open');
    },

    _onTypeChange(type) {
        document.getElementById('mcp-stdio-fields').style.display = type === 'stdio' ? 'flex' : 'none';
        document.getElementById('mcp-sse-fields').style.display = type === 'sse' ? 'flex' : 'none';
    },

    _resetForm() {
        ['mcp-new-name','mcp-new-command','mcp-new-args','mcp-new-env','mcp-new-url','mcp-new-description']
            .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
        document.getElementById('mcp-new-type').value = 'stdio';
        this._onTypeChange('stdio');
    },

    /** Load servers and update UI */
    async refresh() {
        await this._checkStatus();
        await this._loadServers();
    },

    async _checkStatus() {
        try {
            const res = await fetch('/api/mcp/status');
            const data = await res.json();
            const bar = document.getElementById('mcp-status-bar');
            if (data.available) {
                bar.className = 'mcp-status-bar available';
                bar.textContent = 'Paquete MCP disponible';
            } else {
                bar.className = 'mcp-status-bar unavailable';
                bar.textContent = data.message || 'MCP no disponible';
            }
        } catch {
            /* server may not be running yet */
        }
    },

    async _loadServers() {
        try {
            const res = await fetch('/api/mcp/servers');
            this.servers = await res.json();
            this._renderServers();
            this._updateHeaderBadge();
        } catch (err) {
            document.getElementById('mcp-server-list').innerHTML =
                '<div class="mcp-empty">Error al cargar servidores</div>';
        }
    },

    _updateHeaderBadge() {
        const btn = document.getElementById('mcp-open-btn');
        if (!btn) return;
        const existing = btn.querySelector('.mcp-count-badge');
        if (existing) existing.remove();

        const connected = this.servers.filter(s => s.connected).length;
        if (connected > 0) {
            const badge = document.createElement('span');
            badge.className = 'mcp-count-badge';
            badge.textContent = connected;
            btn.appendChild(badge);
        }
    },

    _renderServers() {
        const list = document.getElementById('mcp-server-list');

        if (this.servers.length === 0) {
            list.innerHTML = '<div class="mcp-empty">No hay servidores configurados.<br>Agrega uno con el botón de arriba.</div>';
            return;
        }

        list.innerHTML = '';
        this.servers.forEach(server => {
            list.appendChild(this._buildServerCard(server));
        });
    },

    _buildServerCard(server) {
        const card = document.createElement('div');
        card.className = 'mcp-server-card' +
            (server.connected ? ' connected' : '') +
            (!server.enabled ? ' disabled' : '');
        card.dataset.name = server.name;

        const statusClass = server.connected ? 'connected' : '';
        const toolCount = server.tool_count || 0;

        // Build info lines
        let infoLines = '';
        if (server.type === 'stdio') {
            const cmd = [server.command, ...(server.args || [])].filter(Boolean).join(' ');
            infoLines = `<span><span class="info-label">cmd</span>${this._escHtml(cmd)}</span>`;
        } else if (server.type === 'sse') {
            infoLines = `<span><span class="info-label">url</span>${this._escHtml(server.url || '')}</span>`;
        }
        if (server.description) {
            infoLines += `<span><span class="info-label">desc</span>${this._escHtml(server.description)}</span>`;
        }

        // Tools chips
        const toolsHtml = (server.tools || [])
            .map(t => `<span class="mcp-tool-chip">${this._escHtml(t.name)}</span>`)
            .join('');

        card.innerHTML = `
            <div class="mcp-card-header" data-target="card-body-${this._safeId(server.name)}">
                <span class="mcp-server-status ${statusClass}"></span>
                <span class="mcp-server-name">${this._escHtml(server.name)}</span>
                <div class="mcp-server-badges">
                    <span class="mcp-badge mcp-badge-type">${server.type}</span>
                    ${toolCount > 0 ? `<span class="mcp-badge mcp-badge-tools">${toolCount} herramientas</span>` : ''}
                    ${!server.enabled ? '<span class="mcp-badge mcp-badge-disabled">desactivado</span>' : ''}
                </div>
                <svg class="mcp-card-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="6 9 12 15 18 9"/>
                </svg>
            </div>
            <div class="mcp-card-body" id="card-body-${this._safeId(server.name)}">
                <div class="mcp-server-info">${infoLines}</div>
                ${toolsHtml ? `<div class="mcp-tools-list">${toolsHtml}</div>` : ''}
                <div class="mcp-card-actions">
                    <label class="mcp-toggle-label">
                        <span class="mcp-switch">
                            <input type="checkbox" class="mcp-enable-toggle" data-name="${this._escHtml(server.name)}" ${server.enabled ? 'checked' : ''}>
                            <span class="mcp-switch-track"></span>
                        </span>
                        Habilitado
                    </label>
                    <button class="btn btn-secondary btn-sm mcp-connect-btn" data-name="${this._escHtml(server.name)}">
                        ${server.connected ? 'Reconectar' : 'Conectar'}
                    </button>
                    <button class="btn btn-danger btn-sm mcp-delete-btn" data-name="${this._escHtml(server.name)}">
                        Eliminar
                    </button>
                </div>
            </div>
        `;

        // Toggle collapse
        card.querySelector('.mcp-card-header').addEventListener('click', (e) => {
            if (e.target.closest('button, input, label')) return;
            const bodyId = `card-body-${this._safeId(server.name)}`;
            const body = document.getElementById(bodyId);
            const chevron = card.querySelector('.mcp-card-chevron');
            const open = body.classList.toggle('open');
            chevron.classList.toggle('open', open);
        });

        // Enable toggle
        card.querySelector('.mcp-enable-toggle').addEventListener('change', async (e) => {
            await this._setEnabled(server.name, e.target.checked);
        });

        // Connect button
        card.querySelector('.mcp-connect-btn').addEventListener('click', () => {
            this._connectServer(server.name);
        });

        // Delete button
        card.querySelector('.mcp-delete-btn').addEventListener('click', () => {
            this._deleteServer(server.name);
        });

        return card;
    },

    /** Connect all enabled servers */
    async _connectAll() {
        const btn = document.getElementById('mcp-connect-all');
        btn.disabled = true;
        btn.textContent = 'Conectando...';
        try {
            const res = await fetch('/api/mcp/connect-all', { method: 'POST' });
            const data = await res.json();
            const results = data.results || {};
            const msgs = Object.entries(results).map(([name, r]) =>
                r.status === 'ok' ? `${name}: ${r.tools} herramientas` : `${name}: ${r.error || r.status}`
            );
            Utils.showToast(msgs.join(' | ') || 'Conectado', 'success');
        } catch {
            Utils.showToast('Error conectando servidores', 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="13 2 13 9 20 9"/><path d="M11 2H4a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-7"/></svg> Conectar todos`;
            await this._loadServers();
        }
    },

    async _connectServer(name) {
        const card = document.querySelector(`.mcp-server-card[data-name="${name}"]`);
        const btn = card?.querySelector('.mcp-connect-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Conectando...'; }

        // Show connecting state
        const dot = card?.querySelector('.mcp-server-status');
        if (dot) dot.className = 'mcp-server-status connecting';

        try {
            const res = await fetch(`/api/mcp/servers/${encodeURIComponent(name)}/connect`, { method: 'POST' });
            const data = await res.json();
            if (res.ok) {
                Utils.showToast(`${name}: ${data.tool_count} herramientas descubiertas`, 'success');
            } else {
                Utils.showToast(`Error: ${data.detail || 'Fallo al conectar'}`, 'error');
            }
        } catch {
            Utils.showToast(`Error conectando a ${name}`, 'error');
        } finally {
            await this._loadServers();
        }
    },

    async _setEnabled(name, enabled) {
        try {
            await fetch(`/api/mcp/servers/${encodeURIComponent(name)}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled })
            });
            await this._loadServers();
        } catch {
            Utils.showToast('Error actualizando servidor', 'error');
        }
    },

    async _deleteServer(name) {
        if (!confirm(`¿Eliminar el servidor "${name}"?`)) return;
        try {
            const res = await fetch(`/api/mcp/servers/${encodeURIComponent(name)}`, { method: 'DELETE' });
            if (res.ok) {
                Utils.showToast(`Servidor "${name}" eliminado`, 'success');
                await this._loadServers();
            } else {
                Utils.showToast('Error al eliminar', 'error');
            }
        } catch {
            Utils.showToast('Error al eliminar servidor', 'error');
        }
    },

    async _submitAdd() {
        const name = document.getElementById('mcp-new-name').value.trim();
        const type = document.getElementById('mcp-new-type').value;
        if (!name) { Utils.showToast('El nombre es obligatorio', 'error'); return; }

        const payload = { name, type, enabled: true };
        payload.description = document.getElementById('mcp-new-description').value.trim();

        if (type === 'stdio') {
            const cmd = document.getElementById('mcp-new-command').value.trim();
            if (!cmd) { Utils.showToast('El comando es obligatorio para tipo stdio', 'error'); return; }
            payload.command = cmd;
            payload.args = document.getElementById('mcp-new-args').value
                .split(',').map(s => s.trim()).filter(Boolean);
            payload.env = this._parseEnv(document.getElementById('mcp-new-env').value);
        } else {
            const url = document.getElementById('mcp-new-url').value.trim();
            if (!url) { Utils.showToast('La URL es obligatoria para tipo SSE', 'error'); return; }
            payload.url = url;
        }

        const saveBtn = document.getElementById('mcp-form-save');
        saveBtn.disabled = true;
        saveBtn.textContent = 'Guardando...';

        try {
            const res = await fetch('/api/mcp/servers', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (res.ok) {
                Utils.showToast(`Servidor "${name}" agregado`, 'success');
                this._closeAddForm();
                await this._loadServers();
            } else {
                Utils.showToast(`Error: ${data.detail || 'Fallo al agregar'}`, 'error');
            }
        } catch {
            Utils.showToast('Error al agregar servidor', 'error');
        } finally {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Agregar servidor';
        }
    },

    /** Parse "KEY=VALUE\nKEY2=VALUE2" into object */
    _parseEnv(raw) {
        const env = {};
        raw.split('\n').forEach(line => {
            const idx = line.indexOf('=');
            if (idx > 0) {
                const k = line.slice(0, idx).trim();
                const v = line.slice(idx + 1).trim();
                if (k) env[k] = v;
            }
        });
        return env;
    },

    _escHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    },

    _safeId(name) {
        return name.replace(/[^a-zA-Z0-9_-]/g, '_');
    }
};

window.MCP = MCP;
