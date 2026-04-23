
/**
 * Explorer module — VS Code-style activity bar, side panel, and file tree.
 */

const Explorer = {
    activePanel: 'explorer',
    currentPath: null,
    workspacePath: null,
    contextTarget: null,   // {path, type} for context menu
    _resizing: false,
    _resizeStartX: 0,
    _resizeStartW: 0,

    init() {
        this._bindActivityBar();
        this._bindResize();
        this._buildContextMenu();
        this._bindGlobalClose();
        this._bindSidebarToggle();
        this.setPanel('explorer');
        // File tree loads after we know the workspace (Sidebar.onConnected sets it)
    },

    // -------------------------------------------------------------------------
    // Activity bar
    // -------------------------------------------------------------------------

    _bindActivityBar() {
        document.querySelectorAll('.activity-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const panel = btn.dataset.panel;
                if (this.activePanel === panel && !document.getElementById('side-panel').classList.contains('collapsed')) {
                    this._collapseSidePanel();
                } else {
                    this.setPanel(panel);
                    this._expandSidePanel();
                }
            });
        });
    },

    setPanel(name) {
        this.activePanel = name;

        // Update buttons
        document.querySelectorAll('.activity-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.panel === name);
        });

        // Update panels
        document.querySelectorAll('.panel').forEach(p => {
            p.classList.toggle('active', p.dataset.panel === name);
        });

        // If switching to explorer, load tree if not loaded yet
        if (name === 'explorer' && this.currentPath) {
            const tree = document.getElementById('file-tree');
            if (tree && !tree.hasChildNodes()) {
                this._loadTree(this.currentPath, tree, 0);
            }
        }
    },

    _collapseSidePanel() {
        document.getElementById('side-panel').classList.add('collapsed');
        document.querySelectorAll('.activity-btn').forEach(b => b.classList.remove('active'));
    },

    _expandSidePanel() {
        document.getElementById('side-panel').classList.remove('collapsed');
    },

    // -------------------------------------------------------------------------
    // Mobile sidebar toggle (reuses header button)
    // -------------------------------------------------------------------------

    _bindSidebarToggle() {
        const btn = document.getElementById('sidebar-toggle');
        if (!btn) return;
        btn.addEventListener('click', () => {
            const panel = document.getElementById('side-panel');
            panel.classList.toggle('mobile-open');
        });

        // Close on outside click (mobile)
        document.addEventListener('click', (e) => {
            if (window.innerWidth > 768) return;
            const panel = document.getElementById('side-panel');
            const btn = document.getElementById('sidebar-toggle');
            if (panel.classList.contains('mobile-open') &&
                !panel.contains(e.target) && !btn.contains(e.target)) {
                panel.classList.remove('mobile-open');
            }
        });
    },

    // -------------------------------------------------------------------------
    // Panel resize (drag handle)
    // -------------------------------------------------------------------------

    _bindResize() {
        const handle = document.getElementById('panel-resize');
        const panel = document.getElementById('side-panel');
        if (!handle || !panel) return;

        handle.addEventListener('mousedown', (e) => {
            this._resizing = true;
            this._resizeStartX = e.clientX;
            this._resizeStartW = panel.offsetWidth;
            handle.classList.add('dragging');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!this._resizing) return;
            const delta = e.clientX - this._resizeStartX;
            const newW = Math.max(160, Math.min(600, this._resizeStartW + delta));
            panel.style.width = newW + 'px';
        });

        document.addEventListener('mouseup', () => {
            if (!this._resizing) return;
            this._resizing = false;
            handle.classList.remove('dragging');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            Utils.storage.set('sidePanelWidth', document.getElementById('side-panel').offsetWidth);
        });

        // Restore saved width
        const saved = Utils.storage.get('sidePanelWidth');
        if (saved && saved >= 160 && saved <= 600) {
            panel.style.width = saved + 'px';
        }
    },

    // -------------------------------------------------------------------------
    // Panel sections (collapsible headers inside Config panel)
    // -------------------------------------------------------------------------

    initPanelSections() {
        document.querySelectorAll('.panel-section-header').forEach(header => {
            const targetId = header.dataset.target;
            const chevron = header.querySelector('.panel-section-chevron');
            if (!targetId) return;

            const saved = Utils.storage.get('panelSection_' + targetId, true);
            this._setSectionOpen(header, targetId, chevron, saved);

            header.addEventListener('click', () => {
                const body = document.getElementById(targetId);
                if (!body) return;
                const isOpen = !body.classList.contains('collapsed');
                this._setSectionOpen(header, targetId, chevron, !isOpen);
                Utils.storage.set('panelSection_' + targetId, !isOpen);
            });
        });
    },

    _setSectionOpen(header, targetId, chevron, open) {
        const body = document.getElementById(targetId);
        if (!body) return;
        body.classList.toggle('collapsed', !open);
        if (chevron) chevron.classList.toggle('collapsed', !open);
    },

    // -------------------------------------------------------------------------
    // File Tree
    // -------------------------------------------------------------------------

    /** Called by Sidebar after workspace is known */
    setWorkspace(path) {
        this.workspacePath = path;
        this.currentPath = path;
        this._updateWorkspaceBar(path);

        // Reload tree root
        const tree = document.getElementById('file-tree');
        if (tree) {
            tree.innerHTML = '';
            this._loadTree(path, tree, 0);
        }
    },

    _updateWorkspaceBar(path) {
        const el = document.getElementById('explorer-workspace-path');
        if (el) el.textContent = path || '~';
    },

    /** Load directory contents and append tree items into container */
    async _loadTree(path, container, depth) {
        container.innerHTML = '<div class="file-tree-loading">Cargando...</div>';

        try {
            const res = await fetch('/api/files?path=' + encodeURIComponent(path));
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();

            container.innerHTML = '';
            this.currentPath = data.path;

            if (data.items.length === 0) {
                container.innerHTML = '<div class="file-tree-empty">Carpeta vacía</div>';
                return;
            }

            // "Go up" row at root level
            if (depth === 0 && data.parent) {
                container.appendChild(this._makeUpRow(data.parent));
            }

            data.items.forEach(item => {
                container.appendChild(this._makeTreeItem(item, depth));
            });
        } catch (err) {
            container.innerHTML = `<div class="file-tree-error">Error: ${Utils.escapeHtml(String(err))}</div>`;
        }
    },

    _makeUpRow(parentPath) {
        const row = document.createElement('div');
        row.className = 'tree-item-row';
        row.style.paddingLeft = '8px';
        row.title = parentPath;
        row.innerHTML = `
            <span class="tree-chevron-spacer"></span>
            <span class="tree-icon">${this._svgFolder(false)}</span>
            <span class="tree-name" style="color:var(--text-tertiary)">.. (subir)</span>
        `;
        row.addEventListener('click', () => {
            this._loadTree(parentPath, document.getElementById('file-tree'), 0);
        });
        return row;
    },

    _makeTreeItem(item, depth) {
        const wrap = document.createElement('div');
        wrap.className = 'tree-item';
        wrap.dataset.path = item.path;
        wrap.dataset.type = item.type;

        const isWorkspace = item.path === this.workspacePath;
        const indentPx = 8 + depth * 16;

        const row = document.createElement('div');
        row.className = 'tree-item-row' + (isWorkspace ? ' workspace' : '');
        row.title = item.path;

        row.innerHTML = `
            <span class="tree-indent" style="width:${indentPx}px"></span>
            ${item.type === 'dir'
                ? `<span class="tree-chevron">${this._svgChevron()}</span>`
                : `<span class="tree-chevron-spacer"></span>`}
            <span class="tree-icon">${item.type === 'dir' ? this._svgFolder(false) : this._svgFile(item.name)}</span>
            <span class="tree-name${item.hidden ? ' hidden-file' : ''}">${Utils.escapeHtml(item.name)}</span>
            ${isWorkspace ? '<span class="tree-workspace-badge">WS</span>' : ''}
        `;

        // Children container (lazy)
        const children = document.createElement('div');
        children.className = 'tree-children';
        let loaded = false;
        let open = false;

        if (item.type !== 'dir') {
            // Double-click on file → open viewer
            row.addEventListener('dblclick', (e) => {
                e.preventDefault();
                FileViewer.open(item.path, item.name);
            });
        }

        if (item.type === 'dir') {
            // Single click → expand/collapse
            row.addEventListener('click', async (e) => {
                open = !open;
                children.classList.toggle('open', open);
                const chevron = row.querySelector('.tree-chevron');
                chevron.classList.toggle('open', open);

                if (open && !loaded) {
                    loaded = true;
                    children.innerHTML = '<div class="tree-loading">Cargando...</div>';
                    try {
                        const res = await fetch('/api/files?path=' + encodeURIComponent(item.path));
                        if (!res.ok) throw new Error();
                        const data = await res.json();
                        children.innerHTML = '';
                        data.items.forEach(child => {
                            children.appendChild(this._makeTreeItem(child, depth + 1));
                        });
                        if (data.items.length === 0) {
                            children.innerHTML = '<div class="file-tree-empty" style="padding-left:' + (indentPx + 32) + 'px">Vacía</div>';
                        }
                    } catch {
                        children.innerHTML = '<div class="file-tree-error">Error</div>';
                    }
                }

                // Update folder icon
                row.querySelector('.tree-icon').innerHTML = this._svgFolder(open);
            });

            // Double-click → set as workspace
            row.addEventListener('dblclick', (e) => {
                e.preventDefault();
                this._setWorkspace(item.path);
            });
        }

        // Right-click → context menu
        row.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            this.contextTarget = item;
            this._showContextMenu(e.clientX, e.clientY, item.type === 'dir');
        });

        wrap.appendChild(row);
        wrap.appendChild(children);
        return wrap;
    },

    /** Navigate the tree root to a new path (from "Go up" or path bar) */
    navigateTo(path) {
        const tree = document.getElementById('file-tree');
        if (tree) this._loadTree(path, tree, 0);
    },

    // -------------------------------------------------------------------------
    // Set workspace
    // -------------------------------------------------------------------------

    async _setWorkspace(path) {
        if (!wsManager?.sessionId) {
            Utils.showToast('Conecta primero una sesión', 'error');
            return;
        }
        try {
            const res = await fetch(`/api/sessions/${wsManager.sessionId}/config`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workspace_root: path })
            });
            if (res.ok) {
                this.workspacePath = path;
                this._updateWorkspaceBar(path);
                // Also update Config panel workspace display
                const wp = document.getElementById('workspace-path');
                if (wp) wp.textContent = Utils.truncatePath(path, 40);
                Utils.storage.set('settings', {
                    ...(Utils.storage.get('settings') || {}),
                    workspacePath: path
                });
                Utils.showToast('Workspace actualizado: ' + path, 'success');
                // Refresh tree to update workspace badge
                const tree = document.getElementById('file-tree');
                if (tree) this._loadTree(this.currentPath || path, tree, 0);
            }
        } catch {
            Utils.showToast('Error al cambiar workspace', 'error');
        }
    },

    // -------------------------------------------------------------------------
    // Context Menu
    // -------------------------------------------------------------------------

    _buildContextMenu() {
        const menu = document.createElement('div');
        menu.id = 'explorer-context-menu';
        menu.className = 'context-menu';
        menu.style.display = 'none';
        menu.innerHTML = `
            <div class="context-menu-item" id="ctx-set-workspace">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
                    <polyline points="9 22 9 12 15 12 15 22"/>
                </svg>
                Establecer como workspace
            </div>
            <div class="context-menu-item" id="ctx-open-in-tree">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                </svg>
                Abrir carpeta en explorador
            </div>
            <div class="context-menu-separator"></div>
            <div class="context-menu-item" id="ctx-copy-path">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                </svg>
                Copiar ruta
            </div>
            <div class="context-menu-item" id="ctx-mention-in-chat">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                </svg>
                Mencionar en chat
            </div>
        `;
        document.body.appendChild(menu);

        document.getElementById('ctx-set-workspace').addEventListener('click', () => {
            if (this.contextTarget) this._setWorkspace(this.contextTarget.path);
            this._hideContextMenu();
        });

        document.getElementById('ctx-open-in-tree').addEventListener('click', () => {
            if (this.contextTarget && this.contextTarget.type === 'dir') {
                this.navigateTo(this.contextTarget.path);
            }
            this._hideContextMenu();
        });

        document.getElementById('ctx-copy-path').addEventListener('click', () => {
            if (this.contextTarget) Utils.copyToClipboard(this.contextTarget.path);
            this._hideContextMenu();
        });

        document.getElementById('ctx-mention-in-chat').addEventListener('click', () => {
            if (this.contextTarget) {
                const input = document.getElementById('message-input');
                if (input) {
                    input.value += (input.value ? ' ' : '') + '`' + this.contextTarget.path + '`';
                    input.focus();
                    if (window.Chat) Chat.updateSendButton();
                }
            }
            this._hideContextMenu();
        });
    },

    _showContextMenu(x, y, isDir) {
        const menu = document.getElementById('explorer-context-menu');
        document.getElementById('ctx-set-workspace').style.display = isDir ? 'flex' : 'none';
        document.getElementById('ctx-open-in-tree').style.display = isDir ? 'flex' : 'none';

        menu.style.display = 'block';
        menu.style.left = x + 'px';
        menu.style.top = y + 'px';

        // Keep menu inside viewport
        requestAnimationFrame(() => {
            const rect = menu.getBoundingClientRect();
            if (rect.right > window.innerWidth) menu.style.left = (x - rect.width) + 'px';
            if (rect.bottom > window.innerHeight) menu.style.top = (y - rect.height) + 'px';
        });
    },

    _hideContextMenu() {
        const menu = document.getElementById('explorer-context-menu');
        if (menu) menu.style.display = 'none';
        this.contextTarget = null;
    },

    _bindGlobalClose() {
        document.addEventListener('click', (e) => {
            const menu = document.getElementById('explorer-context-menu');
            if (menu && !menu.contains(e.target)) this._hideContextMenu();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') this._hideContextMenu();
        });
    },

    // -------------------------------------------------------------------------
    // SVG helpers
    // -------------------------------------------------------------------------

    _svgChevron() {
        return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>`;
    },

    _svgFolder(open) {
        if (open) {
            return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent-warning)" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="2" y1="10" x2="22" y2="10"/></svg>`;
        }
        return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent-warning)" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`;
    },

    _svgFile(name) {
        const ext = (name || '').split('.').pop().toLowerCase();
        const color = {
            py: '#3572A5', js: '#f1e05a', ts: '#2b7489',
            html: '#e34c26', css: '#563d7c', json: '#cbcb41',
            md: '#083fa1', txt: 'currentColor', sh: '#89e051',
            yml: '#cb171e', yaml: '#cb171e', toml: '#9c4221',
        }[ext] || 'var(--text-tertiary)';

        return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>`;
    },
};

window.Explorer = Explorer;

// =============================================================================
// File Viewer
// =============================================================================

const FileViewer = {
    _currentContent: '',

    open(path, name) {
        const overlay = document.getElementById('file-viewer-overlay');
        if (!overlay) return;

        // Reset state
        document.getElementById('file-viewer-loading').style.display = 'flex';
        document.getElementById('file-viewer-error').style.display = 'none';
        document.getElementById('file-viewer-content').style.display = 'none';
        document.getElementById('file-viewer-name').textContent = name || path.split('/').pop();
        document.getElementById('file-viewer-path').textContent = path;
        document.getElementById('file-viewer-meta').textContent = '';
        document.getElementById('file-viewer-icon').innerHTML = Explorer._svgFile(name || path);

        overlay.style.display = 'flex';
        document.body.style.overflow = 'hidden';

        this._fetch(path);
    },

    close() {
        const overlay = document.getElementById('file-viewer-overlay');
        if (overlay) overlay.style.display = 'none';
        document.body.style.overflow = '';
    },

    async _fetch(path) {
        try {
            const res = await fetch('/api/file-content?path=' + encodeURIComponent(path));
            const data = await res.json();

            if (!res.ok) {
                this._showError(data.detail || 'Error al leer el archivo');
                return;
            }

            this._render(data);
        } catch (err) {
            this._showError('Error de red: ' + String(err));
        }
    },

    _render(data) {
        this._currentContent = data.content;

        // Meta info
        const kb = data.size < 1024 ? data.size + ' B' : (data.size / 1024).toFixed(1) + ' KB';
        document.getElementById('file-viewer-meta').textContent =
            `${data.lines} líneas · ${kb} · .${data.ext || 'txt'}`;

        // Build line numbers
        const linesEl = document.getElementById('file-viewer-lines');
        linesEl.innerHTML = Array.from({ length: data.lines }, (_, i) =>
            `<span>${i + 1}</span>`
        ).join('');

        // Syntax highlighting
        const codeEl = document.getElementById('file-viewer-code');
        const escaped = data.content
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
        codeEl.innerHTML = escaped;

        const lang = this._langFromExt(data.ext);
        if (window.hljs && lang) {
            codeEl.className = 'language-' + lang;
            try { hljs.highlightElement(codeEl); } catch (_) {}
        } else if (window.hljs) {
            codeEl.className = '';
            try { hljs.highlightElement(codeEl); } catch (_) {}
        }

        // Sync theme
        this._syncTheme();

        document.getElementById('file-viewer-loading').style.display = 'none';
        document.getElementById('file-viewer-content').style.display = 'flex';
    },

    _showError(msg) {
        document.getElementById('file-viewer-loading').style.display = 'none';
        const el = document.getElementById('file-viewer-error');
        el.textContent = msg;
        el.style.display = 'flex';
    },

    _syncTheme() {
        const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
        const dark = document.getElementById('hljs-theme-dark');
        const light = document.getElementById('hljs-theme-light');
        if (dark) dark.disabled = !isDark;
        if (light) light.disabled = isDark;
    },

    _langFromExt(ext) {
        return {
            py: 'python', js: 'javascript', ts: 'typescript', jsx: 'javascript',
            tsx: 'typescript', html: 'html', css: 'css', json: 'json',
            md: 'markdown', sh: 'bash', bash: 'bash', yml: 'yaml',
            yaml: 'yaml', toml: 'toml', rs: 'rust', go: 'go',
            java: 'java', c: 'c', cpp: 'cpp', h: 'c', hpp: 'cpp',
            rb: 'ruby', php: 'php', sql: 'sql', xml: 'xml',
            dockerfile: 'dockerfile', tf: 'hcl', lua: 'lua',
            r: 'r', scala: 'scala', kt: 'kotlin', swift: 'swift',
        }[ext] || null;
    },

    init() {
        document.getElementById('file-viewer-close')?.addEventListener('click', () => this.close());
        document.getElementById('file-viewer-overlay')?.addEventListener('click', (e) => {
            if (e.target.id === 'file-viewer-overlay') this.close();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && document.getElementById('file-viewer-overlay')?.style.display !== 'none') {
                this.close();
            }
        });
        document.getElementById('file-viewer-copy')?.addEventListener('click', () => {
            if (this._currentContent) {
                Utils.copyToClipboard(this._currentContent);
                Utils.showToast('Contenido copiado', 'success');
            }
        });
    },
};

window.FileViewer = FileViewer;
