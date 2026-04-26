
/**
 * Explorer module — VS Code-style activity bar, side panel, and file tree.
 */

const Explorer = {
    activePanel: 'explorer',
    currentPath: null,
    workspacePath: null,
    contextTarget: null,   // {path, type, name} for context menu
    _resizing: false,
    _resizeStartX: 0,
    _resizeStartW: 0,
    _showHidden: false,
    _useGitignore: true,

    init() {
        this._bindActivityBar();
        this._bindResize();
        this._buildContextMenu();
        this._bindGlobalClose();
        this._bindSidebarToggle();
        this._bindWorkspaceActions();
        ExplorerDialog.init();
        this._bindOsDropZone();
        this._bindChatDropZone();
        this._bindTreeKeyboard();
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
        if (window.FileWatcher) FileWatcher.onWorkspaceChange(path);
        if (window.GitStatus) GitStatus.onWorkspaceChange(path);

        // Reload tree root
        const tree = document.getElementById('file-tree');
        if (tree) {
            tree.innerHTML = '';
            this._loadTree(path, tree, 0);
        }
    },

    _updateWorkspaceBar(path) {
        Breadcrumbs.render(path || '');
    },

    // -------------------------------------------------------------------------
    // Keyboard navigation for the file tree
    // -------------------------------------------------------------------------

    _bindTreeKeyboard() {
        const tree = document.getElementById('file-tree');
        if (!tree) return;

        tree.addEventListener('keydown', (e) => {
            const rows = Array.from(tree.querySelectorAll('.tree-item-row:not(.dragging)'));
            const focused = tree.querySelector('.tree-item-row.focused');
            let idx = focused ? rows.indexOf(focused) : -1;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                idx = Math.min(rows.length - 1, idx + 1);
                this._focusTreeRow(rows, idx, e.shiftKey);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                idx = Math.max(0, idx - 1);
                this._focusTreeRow(rows, idx, e.shiftKey);
            } else if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                if (focused) focused.click();
            } else if (e.key === 'Escape') {
                TreeSelection.clear();
            } else if (e.key === 'a' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                rows.forEach(r => TreeSelection.add(r));
                TreeSelection.updateBar();
            }
        });
    },

    _focusTreeRow(rows, idx, addToSelection) {
        if (idx < 0 || idx >= rows.length) return;
        const row = rows[idx];
        rows.forEach(r => r.classList.remove('focused'));
        row.classList.add('focused');
        row.scrollIntoView({ block: 'nearest' });
        if (addToSelection) {
            TreeSelection.add(row);
            TreeSelection.updateBar();
        }
    },

    _bindWorkspaceActions() {
        document.getElementById('explorer-nav-home')?.addEventListener('click', () => {
            const home = document.getElementById('explorer-workspace-path')?.dataset?.home
                || (location.hostname === 'localhost' ? null : null);
            this.navigateTo(this.workspacePath || '/');
        });

        document.getElementById('explorer-refresh')?.addEventListener('click', () => {
            if (this.currentPath) {
                const tree = document.getElementById('file-tree');
                if (tree) this._loadTree(this.currentPath, tree, 0);
            }
        });

        const toggleBtn = document.getElementById('explorer-toggle-hidden');
        toggleBtn?.addEventListener('click', () => {
            this._showHidden = !this._showHidden;
            toggleBtn.classList.toggle('active', this._showHidden);
            toggleBtn.title = this._showHidden ? 'Ocultar archivos ocultos' : 'Mostrar archivos ocultos';
            if (this.currentPath) {
                const tree = document.getElementById('file-tree');
                if (tree) this._loadTree(this.currentPath, tree, 0);
            }
        });
    },

    /** Load directory contents and append tree items into container */
    async _loadTree(path, container, depth) {
        container.innerHTML = '<div class="file-tree-loading">Cargando...</div>';

        try {
            const params = new URLSearchParams({
                path,
                show_hidden: this._showHidden ? '1' : '0',
                use_gitignore: this._useGitignore ? '1' : '0',
            });
            const res = await fetch('/api/files?' + params);
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

            // Apply git badges after the DOM is populated
            if (depth === 0 && window.GitStatus) {
                GitStatus.onTreeRefreshed(this.workspacePath);
            }
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

        // Single click with modifier → selection
        row.addEventListener('click', (e) => {
            if (e.ctrlKey || e.metaKey) {
                TreeSelection.toggle(row, item);
                return;
            }
            if (e.shiftKey) {
                TreeSelection.extendTo(row, item);
                return;
            }
            // Plain click: clear selection (dirs expand below, files open on dblclick)
            if (TreeSelection.size() > 0) {
                TreeSelection.clear();
            }
        });

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
                if (e.ctrlKey || e.metaKey || e.shiftKey) return; // handled above
                open = !open;
                children.classList.toggle('open', open);
                const chevron = row.querySelector('.tree-chevron');
                chevron.classList.toggle('open', open);

                if (open && !loaded) {
                    loaded = true;
                    children.innerHTML = '<div class="tree-loading">Cargando...</div>';
                    try {
                        const p = new URLSearchParams({
                            path: item.path,
                            show_hidden: Explorer._showHidden ? '1' : '0',
                            use_gitignore: Explorer._useGitignore ? '1' : '0',
                        });
                        const res = await fetch('/api/files?' + p);
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

        // ── Drag source (tree item → chat or another folder) ──
        row.draggable = true;
        row.addEventListener('dragstart', (e) => {
            e.dataTransfer.effectAllowed = 'copyMove';
            e.dataTransfer.setData('application/x-explorer-path', item.path);
            e.dataTransfer.setData('application/x-explorer-type', item.type);
            e.dataTransfer.setData('application/x-explorer-name', item.name);
            row.classList.add('dragging');
        });
        row.addEventListener('dragend', () => {
            row.classList.remove('dragging');
            document.querySelectorAll('.drop-target').forEach(el => el.classList.remove('drop-target'));
        });

        // ── Drop target (folders only — move within tree) ──
        if (item.type === 'dir') {
            row.addEventListener('dragover', (e) => {
                // Only accept drags from our own tree items
                if (!e.dataTransfer.types.includes('application/x-explorer-path')) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                document.querySelectorAll('.drop-target').forEach(el => el.classList.remove('drop-target'));
                row.classList.add('drop-target');
            });
            row.addEventListener('dragleave', (e) => {
                if (!row.contains(e.relatedTarget)) row.classList.remove('drop-target');
            });
            row.addEventListener('drop', async (e) => {
                e.preventDefault();
                row.classList.remove('drop-target');
                const srcPath = e.dataTransfer.getData('application/x-explorer-path');
                if (!srcPath || srcPath === item.path) return;
                try {
                    const res = await fetch('/api/files/move', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ src_path: srcPath, dst_dir: item.path }),
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Error');
                    Utils.showToast(`Movido: ${data.name}`, 'success');
                    Explorer._refreshCurrentTree();
                } catch (err) {
                    Utils.showToast('Error al mover: ' + String(err), 'error');
                }
            });
        }

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
    // Drop zone: OS files → upload to current tree path
    // -------------------------------------------------------------------------

    _bindOsDropZone() {
        const tree = document.getElementById('file-tree');
        if (!tree) return;

        tree.addEventListener('dragover', (e) => {
            // OS files: dataTransfer.files will be populated
            if (!e.dataTransfer.types.includes('Files')) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
            tree.classList.add('os-drag-over');
        });

        tree.addEventListener('dragleave', (e) => {
            if (!tree.contains(e.relatedTarget)) tree.classList.remove('os-drag-over');
        });

        tree.addEventListener('drop', async (e) => {
            tree.classList.remove('os-drag-over');
            // Ignore drops that come from within the tree (handled by folder rows)
            if (e.dataTransfer.types.includes('application/x-explorer-path')) return;
            if (!e.dataTransfer.files.length) return;
            e.preventDefault();

            const uploadDir = this.currentPath;
            if (!uploadDir) {
                Utils.showToast('Selecciona un workspace primero', 'error');
                return;
            }

            await this._uploadFiles(Array.from(e.dataTransfer.files), uploadDir);
        });
    },

    async _uploadFiles(files, dir) {
        const tree = document.getElementById('file-tree');
        // Show progress indicator
        const indicator = document.createElement('div');
        indicator.className = 'tree-upload-indicator';
        indicator.innerHTML = `<div class="tree-upload-spinner"></div><span>Subiendo ${files.length} archivo${files.length > 1 ? 's' : ''}…</span>`;
        if (tree) { tree.style.position = 'relative'; tree.appendChild(indicator); }

        try {
            const form = new FormData();
            files.forEach(f => form.append('files', f));
            const res = await fetch('/api/files/upload?dir=' + encodeURIComponent(dir), {
                method: 'POST',
                body: form,
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error al subir');
            const names = data.uploaded.map(u => u.name).join(', ');
            Utils.showToast(`Subido${data.uploaded.length > 1 ? 's' : ''}: ${names}`, 'success');
            this._refreshCurrentTree();
        } catch (err) {
            Utils.showToast('Error al subir: ' + String(err), 'error');
        } finally {
            indicator.remove();
        }
    },

    // -------------------------------------------------------------------------
    // Drop zone: tree item dragged → chat input (attach)
    // -------------------------------------------------------------------------

    _bindChatDropZone() {
        const inputArea = document.querySelector('.input-area');
        if (!inputArea) return;

        inputArea.addEventListener('dragover', (e) => {
            if (!e.dataTransfer.types.includes('application/x-explorer-path')) return;
            const srcType = e.dataTransfer.getData('application/x-explorer-type') || '';
            // Only allow files (not directories) to be attached
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
            inputArea.classList.add('chat-drop-over');
        });

        inputArea.addEventListener('dragleave', (e) => {
            if (!inputArea.contains(e.relatedTarget)) inputArea.classList.remove('chat-drop-over');
        });

        inputArea.addEventListener('drop', async (e) => {
            inputArea.classList.remove('chat-drop-over');
            const srcPath = e.dataTransfer.getData('application/x-explorer-path');
            const srcType = e.dataTransfer.getData('application/x-explorer-type');
            const srcName = e.dataTransfer.getData('application/x-explorer-name');
            if (!srcPath || srcType === 'dir') return;
            e.preventDefault();
            await Explorer._attachToChat({ path: srcPath, name: srcName, type: 'file' });
        });
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
                this.currentPath = path;
                this._updateWorkspaceBar(path);
                // Also update Config panel workspace display
                const wp = document.getElementById('workspace-path');
                if (wp) wp.textContent = Utils.truncatePath(path, 40);
                Utils.storage.set('settings', {
                    ...(Utils.storage.get('settings') || {}),
                    workspacePath: path
                });
                Utils.showToast('Workspace actualizado: ' + path, 'success');
                if (window.FileWatcher) FileWatcher.onWorkspaceChange(path);
                if (window.GitStatus) GitStatus.onWorkspaceChange(path);
                // Navigate tree to new workspace
                const tree = document.getElementById('file-tree');
                if (tree) this._loadTree(path, tree, 0);
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
            <div class="context-menu-item" id="ctx-new-file">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14 2 14 8 20 8"/>
                    <line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/>
                </svg>
                Nuevo archivo
            </div>
            <div class="context-menu-item" id="ctx-new-folder">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                    <line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/>
                </svg>
                Nueva carpeta
            </div>
            <div class="context-menu-separator"></div>
            <div class="context-menu-item" id="ctx-copy-path">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                </svg>
                Copiar ruta
            </div>
            <div class="context-menu-item" id="ctx-attach-to-chat">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
                </svg>
                Adjuntar al chat
            </div>
            <div class="context-menu-item" id="ctx-mention-in-chat">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                </svg>
                Mencionar en chat
            </div>
            <div class="context-menu-separator"></div>
            <div class="context-menu-item" id="ctx-rename">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
                Renombrar
            </div>
            <div class="context-menu-item" id="ctx-duplicate">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                </svg>
                Duplicar
            </div>
            <div class="context-menu-item danger" id="ctx-delete">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="3 6 5 6 21 6"/>
                    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
                    <path d="M10 11v6M14 11v6"/>
                    <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
                </svg>
                Eliminar
            </div>
        `;
        document.body.appendChild(menu);

        document.getElementById('ctx-set-workspace').addEventListener('click', () => {
            if (this.contextTarget) this._setWorkspace(this.contextTarget.path);
            this._hideContextMenu();
        });

        document.getElementById('ctx-open-in-tree').addEventListener('click', () => {
            if (this.contextTarget?.type === 'dir') this.navigateTo(this.contextTarget.path);
            this._hideContextMenu();
        });

        document.getElementById('ctx-new-file').addEventListener('click', () => {
            const t = this.contextTarget;
            this._hideContextMenu();
            if (!t) return;
            const dir = t.type === 'dir' ? t.path : t.path.substring(0, t.path.lastIndexOf('/'));
            ExplorerDialog.prompt('Nuevo archivo', '', 'Crear', (name) => this._crudCreateFile(dir, name));
        });

        document.getElementById('ctx-new-folder').addEventListener('click', () => {
            const t = this.contextTarget;
            this._hideContextMenu();
            if (!t) return;
            const dir = t.type === 'dir' ? t.path : t.path.substring(0, t.path.lastIndexOf('/'));
            ExplorerDialog.prompt('Nueva carpeta', '', 'Crear', (name) => this._crudCreateDir(dir, name));
        });

        document.getElementById('ctx-copy-path').addEventListener('click', () => {
            if (this.contextTarget) Utils.copyToClipboard(this.contextTarget.path);
            this._hideContextMenu();
        });

        document.getElementById('ctx-attach-to-chat').addEventListener('click', () => {
            if (this.contextTarget?.type === 'file') this._attachToChat(this.contextTarget);
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

        document.getElementById('ctx-rename').addEventListener('click', () => {
            const t = this.contextTarget;
            this._hideContextMenu();
            if (!t) return;
            ExplorerDialog.prompt('Renombrar', t.name, 'Renombrar', (newName) => this._crudRename(t.path, newName));
        });

        document.getElementById('ctx-duplicate').addEventListener('click', () => {
            if (this.contextTarget) this._crudDuplicate(this.contextTarget.path);
            this._hideContextMenu();
        });

        document.getElementById('ctx-delete').addEventListener('click', () => {
            const t = this.contextTarget;
            this._hideContextMenu();
            if (!t) return;
            const label = t.type === 'dir' ? `la carpeta "${t.name}" y todo su contenido` : `el archivo "${t.name}"`;
            ExplorerDialog.confirm(`¿Eliminar ${label}?`, 'Eliminar', () => this._crudDelete(t.path));
        });
    },

    _showContextMenu(x, y, isDir) {
        const menu = document.getElementById('explorer-context-menu');
        document.getElementById('ctx-set-workspace').style.display = isDir ? 'flex' : 'none';
        document.getElementById('ctx-open-in-tree').style.display = isDir ? 'flex' : 'none';
        document.getElementById('ctx-attach-to-chat').style.display = isDir ? 'none' : 'flex';

        menu.style.display = 'block';
        menu.style.left = x + 'px';
        menu.style.top = y + 'px';

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

    // -------------------------------------------------------------------------
    // Attach file to chat
    // -------------------------------------------------------------------------

    async _attachToChat(item) {
        if (!window.Chat) {
            Utils.showToast('Chat no disponible', 'error');
            return;
        }
        try {
            const res = await fetch('/api/file-content?path=' + encodeURIComponent(item.path));
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error al leer el archivo');
            const blob = new Blob([data.content], { type: 'text/plain' });
            const file = new File([blob], item.name, { type: 'text/plain' });
            await Chat.addFileAttachment(file);
            Utils.showToast(`Adjuntado: ${item.name}`, 'success');
        } catch (err) {
            Utils.showToast('Error al adjuntar: ' + String(err), 'error');
        }
    },

    // -------------------------------------------------------------------------
    // CRUD operations
    // -------------------------------------------------------------------------

    async _crudCreateFile(dir, name) {
        if (!name?.trim()) return;
        const path = dir.replace(/\/$/, '') + '/' + name.trim();
        try {
            const res = await fetch('/api/files/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error');
            Utils.showToast(`Archivo creado: ${data.name}`, 'success');
            this._refreshCurrentTree();
        } catch (err) {
            Utils.showToast('Error: ' + String(err), 'error');
        }
    },

    async _crudCreateDir(dir, name) {
        if (!name?.trim()) return;
        const path = dir.replace(/\/$/, '') + '/' + name.trim();
        try {
            const res = await fetch('/api/files/mkdir', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error');
            Utils.showToast(`Carpeta creada: ${data.name}`, 'success');
            this._refreshCurrentTree();
        } catch (err) {
            Utils.showToast('Error: ' + String(err), 'error');
        }
    },

    async _crudRename(path, newName) {
        if (!newName?.trim()) return;
        try {
            const res = await fetch('/api/files/rename', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path, new_name: newName.trim() }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error');
            Utils.showToast(`Renombrado a: ${data.name}`, 'success');
            this._refreshCurrentTree();
        } catch (err) {
            Utils.showToast('Error: ' + String(err), 'error');
        }
    },

    async _crudDelete(path) {
        try {
            const res = await fetch('/api/files/delete?path=' + encodeURIComponent(path), {
                method: 'DELETE',
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error');
            Utils.showToast('Eliminado', 'success');
            this._refreshCurrentTree();
        } catch (err) {
            Utils.showToast('Error: ' + String(err), 'error');
        }
    },

    async _crudDuplicate(path) {
        try {
            const res = await fetch('/api/files/duplicate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error');
            Utils.showToast(`Duplicado como: ${data.name}`, 'success');
            this._refreshCurrentTree();
        } catch (err) {
            Utils.showToast('Error: ' + String(err), 'error');
        }
    },

    _refreshCurrentTree() {
        const tree = document.getElementById('file-tree');
        if (tree && this.currentPath) this._loadTree(this.currentPath, tree, 0);
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
// Explorer Dialog  (prompt / confirm)
// =============================================================================

const ExplorerDialog = {
    _resolve: null,

    init() {
        this._overlay = document.getElementById('explorer-dialog-overlay');
        this._titleEl = document.getElementById('explorer-dialog-title');
        this._inputEl = document.getElementById('explorer-dialog-input');
        this._confirmBtn = document.getElementById('explorer-dialog-confirm');
        this._cancelBtn = document.getElementById('explorer-dialog-cancel');

        if (!this._overlay) return;

        this._cancelBtn.addEventListener('click', () => this._close(null));
        this._confirmBtn.addEventListener('click', () => this._submit());
        this._inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); this._submit(); }
            if (e.key === 'Escape') this._close(null);
        });
        this._overlay.addEventListener('click', (e) => {
            if (e.target === this._overlay) this._close(null);
        });
    },

    // Show input dialog. Calls cb(value) on confirm.
    prompt(title, defaultVal, confirmLabel, cb) {
        this._cb = cb;
        this._mode = 'prompt';
        this._titleEl.textContent = title;
        this._inputEl.value = defaultVal || '';
        this._inputEl.style.display = '';
        this._confirmBtn.textContent = confirmLabel || 'Aceptar';
        this._confirmBtn.classList.remove('danger');
        this._overlay.hidden = false;
        requestAnimationFrame(() => {
            this._inputEl.focus();
            this._inputEl.select();
        });
    },

    // Show confirmation dialog (no input). Calls cb() on confirm.
    confirm(title, confirmLabel, cb) {
        this._cb = cb;
        this._mode = 'confirm';
        this._titleEl.textContent = title;
        this._inputEl.style.display = 'none';
        this._confirmBtn.textContent = confirmLabel || 'Confirmar';
        this._confirmBtn.classList.add('danger');
        this._overlay.hidden = false;
        requestAnimationFrame(() => this._confirmBtn.focus());
    },

    _submit() {
        if (this._mode === 'prompt') {
            const val = this._inputEl.value.trim();
            if (!val) return;
            this._close(val);
        } else {
            this._close(true);
        }
    },

    _close(result) {
        this._overlay.hidden = true;
        this._inputEl.style.display = '';
        this._confirmBtn.classList.remove('danger');
        if (result !== null && result !== undefined && this._cb) {
            this._cb(result);
        }
        this._cb = null;
    },
};

window.ExplorerDialog = ExplorerDialog;

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

// =============================================================================
// Quick Open  (Ctrl+P)
// =============================================================================

const QuickOpen = {
    _selectedIdx: -1,
    _items: [],
    _debounce: null,

    init() {
        this._overlay = document.getElementById('quick-open-overlay');
        this._input   = document.getElementById('quick-open-input');
        this._results = document.getElementById('quick-open-results');

        if (!this._overlay) return;

        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'p') {
                e.preventDefault();
                this.open();
            }
        });

        this._overlay.addEventListener('click', (e) => {
            if (e.target === this._overlay) this.close();
        });

        this._input.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { this.close(); return; }
            if (e.key === 'ArrowDown') { e.preventDefault(); this._move(1); return; }
            if (e.key === 'ArrowUp')   { e.preventDefault(); this._move(-1); return; }
            if (e.key === 'Enter')     { e.preventDefault(); this._confirm(); return; }
        });

        this._input.addEventListener('input', () => {
            clearTimeout(this._debounce);
            this._debounce = setTimeout(() => this._search(), 180);
        });
    },

    open() {
        this._overlay.hidden = false;
        this._input.value = '';
        this._input.focus();
        this._results.innerHTML = '<div class="quick-open-empty">Escribe para buscar archivos</div>';
        this._items = [];
        this._selectedIdx = -1;
        document.body.style.overflow = 'hidden';
    },

    close() {
        this._overlay.hidden = true;
        document.body.style.overflow = '';
        clearTimeout(this._debounce);
    },

    async _search() {
        const q = this._input.value.trim();
        const path = Explorer.workspacePath;

        if (!q) {
            this._results.innerHTML = '<div class="quick-open-empty">Escribe para buscar archivos</div>';
            this._items = [];
            return;
        }
        if (!path) {
            this._results.innerHTML = '<div class="quick-open-empty">Selecciona un workspace primero</div>';
            return;
        }

        this._results.innerHTML = '<div class="quick-open-loading">Buscando...</div>';

        try {
            const res = await fetch('/api/files/search?path=' + encodeURIComponent(path) + '&q=' + encodeURIComponent(q));
            if (!res.ok) throw new Error();
            const data = await res.json();
            this._render(data.items, q);
        } catch {
            this._results.innerHTML = '<div class="quick-open-no-results">Error al buscar</div>';
        }
    },

    _render(items, q) {
        this._items = items;
        this._selectedIdx = items.length ? 0 : -1;

        if (!items.length) {
            this._results.innerHTML = '<div class="quick-open-no-results">Sin resultados para "<b>' + Utils.escapeHtml(q) + '</b>"</div>';
            return;
        }

        this._results.innerHTML = '';
        items.forEach((item, i) => {
            const el = document.createElement('div');
            el.className = 'quick-open-item' + (i === 0 ? ' active' : '');
            el.dataset.idx = i;
            el.innerHTML = `
                <span class="quick-open-item-icon">${Explorer._svgFile(item.name)}</span>
                <span class="quick-open-item-name">${this._highlight(item.name, q)}</span>
                <span class="quick-open-item-rel">${Utils.escapeHtml(item.rel_path)}</span>
            `;
            el.addEventListener('click', () => {
                this._selectedIdx = i;
                this._confirm();
            });
            el.addEventListener('mousemove', () => {
                this._select(i);
            });
            this._results.appendChild(el);
        });
    },

    _highlight(name, q) {
        const escaped = Utils.escapeHtml(name);
        const ql = q.toLowerCase();
        const idx = name.toLowerCase().indexOf(ql);
        if (idx === -1) return escaped;
        return Utils.escapeHtml(name.slice(0, idx))
            + '<mark>' + Utils.escapeHtml(name.slice(idx, idx + q.length)) + '</mark>'
            + Utils.escapeHtml(name.slice(idx + q.length));
    },

    _move(dir) {
        if (!this._items.length) return;
        const next = Math.max(0, Math.min(this._items.length - 1, this._selectedIdx + dir));
        this._select(next);
    },

    _select(idx) {
        const rows = this._results.querySelectorAll('.quick-open-item');
        rows.forEach((r, i) => r.classList.toggle('active', i === idx));
        this._selectedIdx = idx;
        rows[idx]?.scrollIntoView({ block: 'nearest' });
    },

    _confirm() {
        const item = this._items[this._selectedIdx];
        if (!item) return;
        this.close();
        FileViewer.open(item.path, item.name);
    },
};

window.QuickOpen = QuickOpen;

// =============================================================================
// Search Panel  (Ctrl+Shift+F)
// =============================================================================

const SearchPanel = {
    _debounce: null,
    _groupStates: {},   // rel_path → collapsed bool

    init() {
        this._input      = document.getElementById('search-panel-query');
        this._caseCb     = document.getElementById('search-case-sensitive');
        this._status     = document.getElementById('search-panel-status');
        this._results    = document.getElementById('search-panel-results');

        if (!this._input) return;

        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'F') {
                e.preventDefault();
                Explorer.setPanel('search');
                Explorer._expandSidePanel();
                this._input.focus();
            }
        });

        this._input.addEventListener('input', () => {
            clearTimeout(this._debounce);
            this._debounce = setTimeout(() => this._search(), 350);
        });

        this._caseCb.addEventListener('change', () => {
            clearTimeout(this._debounce);
            this._debounce = setTimeout(() => this._search(), 100);
        });
    },

    async _search() {
        const q    = this._input.value.trim();
        const path = Explorer.workspacePath;

        if (!q) {
            this._status.textContent = '';
            this._results.innerHTML = '<div class="search-panel-empty">Escribe para buscar en archivos</div>';
            return;
        }
        if (!path) {
            this._status.textContent = '';
            this._results.innerHTML = '<div class="search-panel-empty">Selecciona un workspace primero</div>';
            return;
        }

        this._status.textContent = 'Buscando…';
        this._results.innerHTML = '';

        try {
            const cs  = this._caseCb.checked ? '1' : '0';
            const url = `/api/files/grep?path=${encodeURIComponent(path)}&q=${encodeURIComponent(q)}&case_sensitive=${cs}`;
            const res = await fetch(url);
            if (!res.ok) throw new Error();
            const data = await res.json();
            this._render(data.groups, q);
        } catch {
            this._status.textContent = 'Error al buscar';
        }
    },

    _render(groups, q) {
        if (!groups.length) {
            this._status.textContent = 'Sin resultados';
            this._results.innerHTML = '<div class="search-panel-no-results">No se encontró ninguna coincidencia</div>';
            return;
        }

        const totalMatches = groups.reduce((s, g) => s + g.matches.length, 0);
        this._status.textContent = `${totalMatches} resultado${totalMatches !== 1 ? 's' : ''} en ${groups.length} archivo${groups.length !== 1 ? 's' : ''}`;
        this._results.innerHTML = '';

        groups.forEach(group => {
            const collapsed = this._groupStates[group.rel_path] ?? false;
            const el = document.createElement('div');
            el.className = 'search-group';

            const header = document.createElement('div');
            header.className = 'search-group-header';
            header.innerHTML = `
                <svg class="search-group-chevron${collapsed ? ' collapsed' : ''}" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <polyline points="9 18 15 12 9 6"/>
                </svg>
                <span class="search-group-filename">${Utils.escapeHtml(group.file_name)}</span>
                <span class="search-group-relpath">${Utils.escapeHtml(group.rel_path)}</span>
                <span class="search-group-count">${group.matches.length}</span>
            `;

            const matchList = document.createElement('div');
            matchList.className = 'search-group-matches' + (collapsed ? ' collapsed' : '');

            header.addEventListener('click', () => {
                const isCollapsed = matchList.classList.toggle('collapsed');
                header.querySelector('.search-group-chevron').classList.toggle('collapsed', isCollapsed);
                this._groupStates[group.rel_path] = isCollapsed;
            });

            group.matches.forEach(m => {
                const row = document.createElement('div');
                row.className = 'search-match-row';
                row.innerHTML = `
                    <span class="search-match-lineno">${m.line_no}</span>
                    <span class="search-match-line">${this._highlightLine(m.line, m.match_start, m.match_end)}</span>
                `;
                row.addEventListener('click', () => {
                    FileViewer.open(group.file_path, group.file_name);
                });
                matchList.appendChild(row);
            });

            el.appendChild(header);
            el.appendChild(matchList);
            this._results.appendChild(el);
        });
    },

    _highlightLine(line, start, end) {
        const esc = Utils.escapeHtml;
        return esc(line.slice(0, start))
            + '<mark>' + esc(line.slice(start, end)) + '</mark>'
            + esc(line.slice(end));
    },
};

window.SearchPanel = SearchPanel;

// =============================================================================
// File Watcher  (WebSocket-based auto-refresh)
// =============================================================================

// =============================================================================
// Breadcrumbs
// =============================================================================

const Breadcrumbs = {
    _container: null,

    init() {
        this._container = document.getElementById('explorer-breadcrumbs');
    },

    render(fullPath) {
        if (!this._container) this._container = document.getElementById('explorer-breadcrumbs');
        if (!this._container) return;
        this._container.innerHTML = '';

        if (!fullPath) return;

        // Split path into segments, build cumulative paths for each crumb
        const parts = fullPath.replace(/\\/g, '/').split('/').filter(Boolean);
        const isAbs = fullPath.startsWith('/');

        // Always show at most the last N segments to avoid overflow
        const MAX_VISIBLE = 4;
        const allParts = isAbs ? ['', ...parts] : parts;  // '' = root '/'
        const start = Math.max(0, allParts.length - MAX_VISIBLE);

        if (start > 0) {
            // Show ellipsis for hidden ancestors
            const ellipsis = document.createElement('span');
            ellipsis.className = 'bc-item';
            ellipsis.title = fullPath;
            ellipsis.textContent = '…';
            // Clicking ellipsis goes to the hidden ancestor
            const hiddenParts = allParts.slice(0, start);
            const hiddenPath = (isAbs ? '/' : '') + hiddenParts.filter(Boolean).join('/');
            ellipsis.addEventListener('click', () => Explorer.navigateTo(hiddenPath));
            this._container.appendChild(ellipsis);
            this._container.appendChild(this._sep());
        }

        allParts.slice(start).forEach((part, i) => {
            const absIdx = start + i;
            // Build cumulative path up to this segment
            const cumParts = allParts.slice(0, absIdx + 1).filter(Boolean);
            const cumPath = (isAbs ? '/' : '') + cumParts.join('/') || '/';
            const isLast = absIdx === allParts.length - 1;
            const label = part === '' ? '/' : part;  // root shows as /

            const crumb = document.createElement('span');
            crumb.className = 'bc-item';
            crumb.textContent = label;
            crumb.title = cumPath;

            if (!isLast) {
                crumb.addEventListener('click', () => Explorer.navigateTo(cumPath));
                this._container.appendChild(crumb);
                this._container.appendChild(this._sep());
            } else {
                this._container.appendChild(crumb);
            }
        });
    },

    _sep() {
        const s = document.createElement('span');
        s.className = 'bc-sep';
        s.textContent = '›';
        s.setAttribute('aria-hidden', 'true');
        return s;
    },
};

window.Breadcrumbs = Breadcrumbs;

// =============================================================================
// TreeSelection  (Ctrl/Shift click + bulk actions)
// =============================================================================

const TreeSelection = {
    // Map<row element, item object>
    _selected: new Map(),
    _lastRow: null,

    init() {
        document.getElementById('sel-attach')?.addEventListener('click', () => this._bulkAttach());
        document.getElementById('sel-copy-paths')?.addEventListener('click', () => this._bulkCopyPaths());
        document.getElementById('sel-delete')?.addEventListener('click', () => this._bulkDelete());
        document.getElementById('sel-clear')?.addEventListener('click', () => this.clear());
    },

    size() { return this._selected.size; },

    toggle(row, item) {
        if (this._selected.has(row)) {
            this._selected.delete(row);
            row.classList.remove('selected');
        } else {
            this._selected.set(row, item);
            row.classList.add('selected');
            this._lastRow = row;
        }
        this.updateBar();
    },

    add(row) {
        const wrap = row.closest('.tree-item');
        if (!wrap) return;
        const item = {
            path: wrap.dataset.path,
            type: wrap.dataset.type,
            name: wrap.querySelector('.tree-name')?.textContent || '',
        };
        this._selected.set(row, item);
        row.classList.add('selected');
        this._lastRow = row;
    },

    extendTo(row, item) {
        if (!this._lastRow) {
            this.toggle(row, item);
            return;
        }
        const tree = document.getElementById('file-tree');
        if (!tree) return;
        const rows = Array.from(tree.querySelectorAll('.tree-item-row'));
        const a = rows.indexOf(this._lastRow);
        const b = rows.indexOf(row);
        if (a === -1 || b === -1) { this.toggle(row, item); return; }
        const [lo, hi] = a < b ? [a, b] : [b, a];
        rows.slice(lo, hi + 1).forEach(r => this.add(r));
        this.updateBar();
    },

    clear() {
        this._selected.forEach((_, row) => row.classList.remove('selected'));
        this._selected.clear();
        this._lastRow = null;
        this.updateBar();
    },

    updateBar() {
        const bar = document.getElementById('explorer-selection-bar');
        const countEl = document.getElementById('selection-count');
        if (!bar) return;
        const n = this._selected.size;
        bar.hidden = n === 0;
        if (countEl) countEl.textContent = `${n} seleccionado${n !== 1 ? 's' : ''}`;

        // Disable attach if any dir is in selection (dirs can't be attached)
        const attachBtn = document.getElementById('sel-attach');
        if (attachBtn) {
            const hasDir = [...this._selected.values()].some(i => i.type === 'dir');
            attachBtn.disabled = hasDir;
            attachBtn.style.opacity = hasDir ? '0.4' : '';
        }
    },

    items() { return [...this._selected.values()]; },

    async _bulkAttach() {
        const files = this.items().filter(i => i.type === 'file');
        for (const item of files) {
            await Explorer._attachToChat(item);
        }
        this.clear();
    },

    _bulkCopyPaths() {
        const paths = this.items().map(i => i.path).join('\n');
        Utils.copyToClipboard(paths);
        Utils.showToast(`${this._selected.size} rutas copiadas`, 'success');
        this.clear();
    },

    async _bulkDelete() {
        const items = this.items();
        const n = items.length;
        ExplorerDialog.confirm(
            `¿Eliminar ${n} elemento${n !== 1 ? 's' : ''}?`,
            'Eliminar',
            async () => {
                for (const item of items) {
                    await Explorer._crudDelete(item.path);
                }
                this.clear();
            }
        );
    },
};

window.TreeSelection = TreeSelection;

// =============================================================================
// GitStatus  (periodic poll + badge overlay)
// =============================================================================

const GitStatus = {
    _timer: null,
    _INTERVAL_MS: 15_000,   // poll every 15 s
    _cache: {},             // rel_path → badge letter
    _isGit: false,

    init() {
        // Triggered by Explorer.setWorkspace and FileWatcher refresh
    },

    onWorkspaceChange(wsPath) {
        clearTimeout(this._timer);
        this._cache = {};
        this._isGit = false;
        this._removeAllBadges();
        if (wsPath) this._poll(wsPath);
    },

    scheduleRefresh(wsPath) {
        clearTimeout(this._timer);
        if (wsPath) this._timer = setTimeout(() => this._poll(wsPath), this._INTERVAL_MS);
    },

    async _poll(wsPath) {
        try {
            const res = await fetch('/api/git/status?path=' + encodeURIComponent(wsPath));
            if (!res.ok) return;
            const data = await res.json();
            this._isGit = data.is_git;
            this._cache = data.files || {};
            this._applyBadges(wsPath);
        } catch {
            // silently skip on network error
        }
        this.scheduleRefresh(wsPath);
    },

    _applyBadges(wsPath) {
        const tree = document.getElementById('file-tree');
        if (!tree) return;
        this._removeAllBadges();
        if (!this._isGit || !Object.keys(this._cache).length) return;

        tree.querySelectorAll('.tree-item').forEach(wrap => {
            const itemPath = wrap.dataset.path;
            if (!itemPath) return;
            let rel;
            try {
                // Compute path relative to wsPath
                if (itemPath.startsWith(wsPath + '/')) {
                    rel = itemPath.slice(wsPath.length + 1);
                } else {
                    rel = itemPath;
                }
            } catch { return; }

            const badge = this._cache[rel];
            if (!badge) return;

            const row = wrap.querySelector('.tree-item-row');
            if (!row) return;

            const span = document.createElement('span');
            span.className = `git-badge git-badge-${badge}`;
            span.textContent = badge === 'U' ? '?' : badge;
            span.title = this._badgeTitle(badge);
            row.appendChild(span);
        });
    },

    _removeAllBadges() {
        document.querySelectorAll('.git-badge').forEach(el => el.remove());
    },

    _badgeTitle(b) {
        return { M: 'Modificado', A: 'Añadido', D: 'Eliminado', R: 'Renombrado', C: 'Copiado', U: 'Sin seguimiento', X: 'Conflicto' }[b] || b;
    },

    // Called from FileWatcher after a tree refresh so badges get re-applied
    onTreeRefreshed(wsPath) {
        if (wsPath && this._isGit) this._applyBadges(wsPath);
    },
};

window.GitStatus = GitStatus;

const FileWatcher = {
    _watchPath: null,
    _refreshTimer: null,
    _DEBOUNCE_MS: 800,

    init() {
        if (!window.wsManager) return;

        // Listen for file_changed events pushed by the server
        wsManager.on('file_changed', (payload) => {
            this._scheduleRefresh();
        });

        // When workspace changes in Explorer, tell the server to watch the new path
        wsManager.on('connected', () => {
            if (Explorer.workspacePath) this._startWatch(Explorer.workspacePath);
        });
    },

    // Called by Explorer._setWorkspace after the workspace changes
    onWorkspaceChange(path) {
        this._watchPath = path;
        this._startWatch(path);
    },

    _startWatch(path) {
        if (!path) return;
        this._watchPath = path;
        wsManager.send({ type: 'watch', path });
    },

    _scheduleRefresh() {
        clearTimeout(this._refreshTimer);
        this._refreshTimer = setTimeout(() => {
            const tree = document.getElementById('file-tree');
            if (tree && Explorer.currentPath) {
                Explorer._loadTree(Explorer.currentPath, tree, 0);
            }
            if (SearchPanel._input?.value.trim()) {
                SearchPanel._search();
            }
            // Re-poll git status after file changes
            if (window.GitStatus && Explorer.workspacePath) {
                GitStatus.onWorkspaceChange(Explorer.workspacePath);
            }
        }, this._DEBOUNCE_MS);
    },
};

window.FileWatcher = FileWatcher;
