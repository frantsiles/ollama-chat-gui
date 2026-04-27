/**
 * GitPanel — sidebar Git panel with full repo management.
 */

const GitPanel = {
    _wsPath: null,
    _isGit: false,
    _pollTimer: null,
    _POLL_MS: 20_000,
    _logPage: 1,
    _LOG_PER_PAGE: 10,

    // -------------------------------------------------------------------------
    // Init
    // -------------------------------------------------------------------------

    init() {
        this._bindSectionHeaders();
        this._bindActions();

        // Refresh when the panel becomes active
        document.querySelectorAll('.activity-btn').forEach(btn => {
            if (btn.dataset.panel === 'git') {
                btn.addEventListener('click', () => {
                    if (this._wsPath) this.refresh();
                });
            }
        });

        // Decouple: react to workspace/file changes via event bus
        window.addEventListener('explorer:workspace-changed', ({ detail: { path } }) => {
            this.onWorkspaceChange(path);
        });
        window.addEventListener('explorer:files-changed', () => {
            if (this._wsPath) this.refresh();
        });
    },

    onWorkspaceChange(path) {
        this._wsPath = path;
        this._logPage = 1;
        clearTimeout(this._pollTimer);
        if (path) this.refresh();
    },

    // -------------------------------------------------------------------------
    // Section header collapse/expand
    // -------------------------------------------------------------------------

    _bindSectionHeaders() {
        document.querySelectorAll('.git-section-header').forEach(header => {
            const targetId = header.dataset.target;
            if (!targetId) return;
            header.addEventListener('click', (e) => {
                // Avoid toggling when clicking inline buttons inside the header
                if (e.target.closest('.git-inline-btn')) return;
                const body = document.getElementById(targetId);
                const chevron = header.querySelector('.git-section-chevron');
                if (!body) return;
                const collapsed = body.classList.toggle('git-section-body--collapsed');
                chevron?.classList.toggle('git-section-chevron--collapsed', collapsed);
            });
        });
    },

    // -------------------------------------------------------------------------
    // Action bindings
    // -------------------------------------------------------------------------

    _bindActions() {
        document.getElementById('git-init-btn')?.addEventListener('click', () => this._init());
        document.getElementById('git-refresh-btn')?.addEventListener('click', () => this.refresh());
        document.getElementById('git-push-btn')?.addEventListener('click', () => this._push());
        document.getElementById('git-pull-btn')?.addEventListener('click', () => this._pull());
        document.getElementById('git-commit-btn')?.addEventListener('click', () => this._commit());

        document.getElementById('git-stage-all-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            this._stageAll();
        });
        document.getElementById('git-unstage-all-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            this._unstageAll();
        });

        document.getElementById('git-edit-user-btn')?.addEventListener('click', () => this._showUserEdit());
        document.getElementById('git-config-cancel')?.addEventListener('click', () => this._hideUserEdit());
        document.getElementById('git-config-save')?.addEventListener('click', () => this._saveUserConfig());

        document.getElementById('git-log-more-btn')?.addEventListener('click', () => {
            this._logPage++;
            this._loadLog();
        });

        document.getElementById('git-diff-close')?.addEventListener('click', () => {
            document.getElementById('git-diff-viewer').hidden = true;
        });

        document.getElementById('git-add-remote-btn')?.addEventListener('click', () => this._showAddRemote(false));
        document.getElementById('git-edit-remote-btn')?.addEventListener('click', () => this._showAddRemote(true));
        document.getElementById('git-remove-remote-btn')?.addEventListener('click', () => this._removeRemote());
        document.getElementById('git-add-remote-cancel')?.addEventListener('click', () => this._hideAddRemote());
        document.getElementById('git-add-remote-save')?.addEventListener('click', () => this._saveRemote());

        document.getElementById('git-create-repo-cancel')?.addEventListener('click', () => this._hideCreateRepoForm());
        document.getElementById('git-create-repo-save')?.addEventListener('click', () => this._createGitHubRepo());
    },

    // -------------------------------------------------------------------------
    // Main refresh
    // -------------------------------------------------------------------------

    async refresh() {
        if (!this._wsPath) return;
        clearTimeout(this._pollTimer);

        const [infoData, changesData] = await Promise.all([
            this._api('GET', `/api/git/info?path=${enc(this._wsPath)}`),
            this._api('GET', `/api/git/changes?path=${enc(this._wsPath)}`),
        ]);

        this._isGit = infoData?.is_git ?? false;
        this._renderState(infoData, changesData);

        if (this._isGit) {
            this._loadLog();
            this._updateActivityBadge(
                (changesData?.staged?.length ?? 0) +
                (changesData?.unstaged?.length ?? 0) +
                (changesData?.untracked?.length ?? 0)
            );
        }

        this._pollTimer = setTimeout(() => this.refresh(), this._POLL_MS);
    },

    _renderState(info, changes) {
        const noWs  = document.getElementById('git-no-workspace');
        const noRepo = document.getElementById('git-no-repo');
        const repoInfo = document.getElementById('git-repo-info');
        const userSec = document.getElementById('git-user-section');
        const sections = ['git-staged-section','git-commit-section','git-unstaged-section',
                          'git-untracked-section','git-log-section'];

        if (!this._wsPath) {
            noWs.hidden = false; noRepo.hidden = true; repoInfo.hidden = true;
            userSec.hidden = true;
            sections.forEach(id => { const el = document.getElementById(id); if (el) el.hidden = true; });
            return;
        }

        noWs.hidden = true;

        if (!this._isGit) {
            noRepo.hidden = false; repoInfo.hidden = true; userSec.hidden = true;
            sections.forEach(id => { const el = document.getElementById(id); if (el) el.hidden = true; });
            return;
        }

        noRepo.hidden = true;
        repoInfo.hidden = false;
        userSec.hidden = false;
        sections.forEach(id => { const el = document.getElementById(id); if (el) el.hidden = false; });

        this._renderInfo(info);
        this._renderUser(info);
        this._renderChanges(changes);
    },

    // -------------------------------------------------------------------------
    // Repo info header
    // -------------------------------------------------------------------------

    _renderInfo(info) {
        if (!info) return;

        document.getElementById('git-branch-name').textContent = info.branch || 'HEAD';

        const syncBadges = document.getElementById('git-sync-badges');
        syncBadges.innerHTML = '';
        if (info.ahead > 0) {
            const b = document.createElement('span');
            b.className = 'git-sync-badge ahead';
            b.textContent = `↑${info.ahead}`;
            b.title = `${info.ahead} commit(s) por delante`;
            syncBadges.appendChild(b);
        }
        if (info.behind > 0) {
            const b = document.createElement('span');
            b.className = 'git-sync-badge behind';
            b.textContent = `↓${info.behind}`;
            b.title = `${info.behind} commit(s) por detrás`;
            syncBadges.appendChild(b);
        }

        const remoteRow = document.getElementById('git-remote-row');
        const remoteUrl = document.getElementById('git-remote-url');
        const noRemoteRow = document.getElementById('git-no-remote-row');
        if (info.remote_url) {
            remoteUrl.textContent = info.remote_url;
            remoteUrl.title = info.remote_url;
            remoteRow.hidden = false;
            if (noRemoteRow) noRemoteRow.hidden = true;
        } else {
            remoteRow.hidden = true;
            if (noRemoteRow) noRemoteRow.hidden = false;
        }
        // Hide the add-remote form whenever we re-render info
        this._hideAddRemote();
    },

    // -------------------------------------------------------------------------
    // User info
    // -------------------------------------------------------------------------

    _renderUser(info) {
        if (!info) return;
        const el = document.getElementById('git-user-info');
        if (!info.user_name && !info.user_email) {
            el.innerHTML = '<em>Sin identidad configurada</em>';
        } else {
            el.innerHTML =
                (info.user_name  ? `<strong>${esc(info.user_name)}</strong><br>` : '') +
                (info.user_email ? `<span>${esc(info.user_email)}</span>` : '');
        }
    },

    _showUserEdit() {
        const infoEl = document.getElementById('git-user-info');
        const editEl = document.getElementById('git-user-edit');
        const btn    = document.getElementById('git-edit-user-btn');
        // Pre-fill
        const name = infoEl.querySelector('strong')?.textContent || '';
        const email = infoEl.querySelector('span')?.textContent || '';
        document.getElementById('git-config-name').value = name;
        document.getElementById('git-config-email').value = email;
        infoEl.hidden = true;
        editEl.hidden = false;
        btn.hidden = true;
        document.getElementById('git-config-name').focus();
    },

    _hideUserEdit() {
        document.getElementById('git-user-info').hidden = false;
        document.getElementById('git-user-edit').hidden = true;
        document.getElementById('git-edit-user-btn').hidden = false;
    },

    async _saveUserConfig() {
        const name  = document.getElementById('git-config-name').value.trim();
        const email = document.getElementById('git-config-email').value.trim();
        if (!name && !email) { this._hideUserEdit(); return; }
        const ok = await this._api('POST', '/api/git/config', {
            path: this._wsPath, user_name: name, user_email: email,
        });
        if (ok) {
            Utils.showToast('Identidad guardada', 'success');
            this._hideUserEdit();
            this.refresh();
        }
    },

    // -------------------------------------------------------------------------
    // Changes (staged / unstaged / untracked)
    // -------------------------------------------------------------------------

    _renderChanges(data) {
        if (!data) return;

        const staged   = data.staged   || [];
        const unstaged = data.unstaged || [];
        const untracked = data.untracked || [];

        // Update counts
        document.getElementById('git-staged-count').textContent   = staged.length;
        document.getElementById('git-unstaged-count').textContent = unstaged.length;
        document.getElementById('git-untracked-count').textContent = untracked.length;

        // Render each list
        this._renderFileList('git-staged-list',   staged,   'staged');
        this._renderFileList('git-unstaged-list', unstaged, 'unstaged');
        this._renderFileList('git-untracked-list', untracked, 'untracked');

        // Commit button: enable only when there are staged changes
        const commitBtn = document.getElementById('git-commit-btn');
        if (commitBtn) commitBtn.disabled = staged.length === 0;
    },

    _renderFileList(containerId, files, kind) {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = '';

        if (!files.length) {
            const empty = document.createElement('div');
            empty.className = 'git-file-row';
            empty.style.color = 'var(--text-tertiary)';
            empty.style.cursor = 'default';
            empty.textContent = 'Sin cambios';
            container.appendChild(empty);
            return;
        }

        files.forEach(f => {
            const row = document.createElement('div');
            row.className = 'git-file-row';
            row.title = f.path;

            const badge = kind === 'staged'    ? f.x :
                          kind === 'unstaged'  ? f.y :
                          '?';
            const badgeLetter = badge === '?' ? 'U' : badge;

            row.innerHTML = `
                <span class="git-file-badge git-file-badge-${badgeLetter}">${badgeLetter}</span>
                <span class="git-file-name">${esc(f.path)}</span>
                <span class="git-file-actions">${this._fileActions(kind)}</span>
            `;

            // Click → show diff
            row.addEventListener('click', (e) => {
                if (e.target.closest('.git-file-action-btn')) return;
                this._showDiff(f.path, kind === 'staged');
            });

            // Action button handlers
            row.querySelectorAll('.git-file-action-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const action = btn.dataset.action;
                    if (action === 'stage')    this._stage([f.path]);
                    if (action === 'unstage')  this._unstage([f.path]);
                    if (action === 'discard')  this._discard([f.path]);
                });
            });

            container.appendChild(row);
        });
    },

    _fileActions(kind) {
        const stageBtn = `
            <button type="button" class="git-file-action-btn" data-action="stage" title="Añadir al stage">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
            </button>`;
        const unstageBtn = `
            <button type="button" class="git-file-action-btn" data-action="unstage" title="Quitar del stage">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
            </button>`;
        const discardBtn = `
            <button type="button" class="git-file-action-btn danger" data-action="discard" title="Descartar cambios">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="3 6 5 6 21 6"/>
                    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
                </svg>
            </button>`;

        if (kind === 'staged')    return unstageBtn;
        if (kind === 'unstaged')  return stageBtn + discardBtn;
        if (kind === 'untracked') return stageBtn;
        return '';
    },

    // -------------------------------------------------------------------------
    // Diff viewer
    // -------------------------------------------------------------------------

    async _showDiff(filePath, staged) {
        const viewer   = document.getElementById('git-diff-viewer');
        const filename = document.getElementById('git-diff-filename');
        const content  = document.getElementById('git-diff-content');

        filename.textContent = filePath + (staged ? ' (staged)' : '');
        content.textContent  = 'Cargando diff…';
        viewer.hidden = false;

        const data = await this._api(
            'GET',
            `/api/git/diff?path=${enc(this._wsPath)}&file=${enc(filePath)}&staged=${staged ? 1 : 0}`,
        );

        if (!data) { content.textContent = 'Error al cargar diff'; return; }

        // Syntax-color the diff
        content.innerHTML = '';
        (data.diff || '(sin cambios)').split('\n').forEach(line => {
            const span = document.createElement('span');
            span.textContent = line + '\n';
            if (line.startsWith('+') && !line.startsWith('+++')) span.className = 'diff-add';
            else if (line.startsWith('-') && !line.startsWith('---')) span.className = 'diff-del';
            else if (line.startsWith('@@')) span.className = 'diff-hunk';
            content.appendChild(span);
        });
    },

    // -------------------------------------------------------------------------
    // Log
    // -------------------------------------------------------------------------

    async _loadLog() {
        const data = await this._api(
            'GET',
            `/api/git/log?path=${enc(this._wsPath)}&n=${this._logPage * this._LOG_PER_PAGE}`,
        );
        if (!data?.is_git) return;

        const list = document.getElementById('git-log-list');
        list.innerHTML = '';

        data.commits.forEach(c => {
            const item = document.createElement('div');
            item.className = 'git-log-item';
            item.innerHTML = `
                <span class="git-log-subject">${esc(c.subject)}</span>
                <div class="git-log-meta">
                    <span class="git-log-hash">${esc(c.hash)}</span>
                    <span>${esc(c.author)}</span>
                    <span>${esc(c.time)}</span>
                    ${c.refs ? `<span class="git-log-refs">${esc(c.refs)}</span>` : ''}
                </div>
            `;
            item.title = c.full_hash;
            list.appendChild(item);
        });

        const moreBtn = document.getElementById('git-log-more-btn');
        if (moreBtn) {
            moreBtn.hidden = data.commits.length < this._logPage * this._LOG_PER_PAGE;
        }
    },

    // -------------------------------------------------------------------------
    // Git operations
    // -------------------------------------------------------------------------

    async _init() {
        const ok = await this._api('POST', '/api/git/init', { path: this._wsPath });
        if (ok) {
            Utils.showToast('Repositorio inicializado', 'success');
            this.refresh();
        }
    },

    async _stage(files) {
        const ok = await this._api('POST', '/api/git/stage', { path: this._wsPath, files });
        if (ok) this.refresh();
    },

    async _stageAll() {
        const ok = await this._api('POST', '/api/git/stage', { path: this._wsPath, files: ['.'] });
        if (ok) this.refresh();
    },

    async _unstage(files) {
        const ok = await this._api('POST', '/api/git/unstage', { path: this._wsPath, files });
        if (ok) this.refresh();
    },

    async _unstageAll() {
        const ok = await this._api('POST', '/api/git/unstage', { path: this._wsPath, files: ['.'] });
        if (ok) this.refresh();
    },

    async _discard(files) {
        ExplorerDialog.confirm(
            `¿Descartar cambios en ${files.length === 1 ? files[0] : files.length + ' archivos'}?`,
            'Descartar',
            async () => {
                const ok = await this._api('POST', '/api/git/discard', { path: this._wsPath, files });
                if (ok) this.refresh();
            }
        );
    },

    async _commit() {
        const msg   = document.getElementById('git-commit-msg').value.trim();
        const amend = document.getElementById('git-amend-check').checked;
        if (!msg) { Utils.showToast('Escribe un mensaje de commit', 'error'); return; }

        const btn = document.getElementById('git-commit-btn');
        btn.disabled = true;

        const ok = await this._api('POST', '/api/git/commit', {
            path: this._wsPath, message: msg, amend,
        });
        if (ok) {
            document.getElementById('git-commit-msg').value = '';
            document.getElementById('git-amend-check').checked = false;
            Utils.showToast('Commit creado', 'success');
            this.refresh();
        }
        btn.disabled = false;
    },

    async _push() {
        const btn = document.getElementById('git-push-btn');
        btn.classList.add('spinning');
        try {
            const res = await fetch('/api/git/push', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: this._wsPath }),
            });
            const data = await res.json();
            if (res.ok) {
                Utils.showToast('Push completado', 'success');
                this.refresh();
            } else if (res.status === 422 && data.detail?.error === 'no_upstream') {
                const noRemote = document.getElementById('git-remote-row')?.hidden !== false;
                if (noRemote) {
                    Utils.showToast('Sin remote configurado. Añade un remote primero.', 'warning');
                    this._showAddRemote(false);
                } else {
                    const branch = data.detail.branch || 'HEAD';
                    ExplorerDialog.confirm(
                        `La rama "${branch}" no tiene upstream. ¿Publicarla en origin?`,
                        'Publicar',
                        () => this._pushWithUpstream()
                    );
                }
            } else if (res.status === 422 && data.detail?.error === 'repo_not_found') {
                this._showCreateRepoForm();
            } else {
                Utils.showToast(data.detail?.message || data.detail || 'Error al hacer push', 'error');
            }
        } catch (err) {
            Utils.showToast('Error de red: ' + String(err), 'error');
        }
        btn.classList.remove('spinning');
    },

    async _pushWithUpstream() {
        const btn = document.getElementById('git-push-btn');
        btn.classList.add('spinning');
        try {
            const res = await fetch('/api/git/push', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: this._wsPath, set_upstream: true }),
            });
            const data = await res.json();
            if (res.ok) {
                Utils.showToast('Rama publicada con éxito', 'success');
                this.refresh();
            } else if (res.status === 422 && data.detail?.error === 'repo_not_found') {
                this._showCreateRepoForm();
            } else {
                Utils.showToast(data.detail?.message || data.detail || 'Error al hacer push', 'error');
            }
        } catch (err) {
            Utils.showToast('Error de red: ' + String(err), 'error');
        }
        btn.classList.remove('spinning');
    },

    _showAddRemote(editing = false) {
        this._editingRemote = editing;
        const noRemote = document.getElementById('git-no-remote-row');
        const remoteRow = document.getElementById('git-remote-row');
        const form = document.getElementById('git-add-remote-form');
        const input = document.getElementById('git-remote-url-input');
        const saveBtn = document.getElementById('git-add-remote-save');
        if (noRemote) noRemote.hidden = true;
        if (remoteRow) remoteRow.hidden = true;
        if (saveBtn) saveBtn.textContent = editing ? 'Actualizar' : 'Añadir';
        // Pre-fill current URL when editing
        input.value = editing ? (document.getElementById('git-remote-url')?.textContent || '') : '';
        form.hidden = false;
        input.focus();
        input.select();
    },

    _hideAddRemote() {
        const form = document.getElementById('git-add-remote-form');
        if (form) form.hidden = true;
        // Restore the correct row based on current state
        const hasRemote = !!(document.getElementById('git-remote-url')?.textContent);
        document.getElementById('git-remote-row').hidden = !hasRemote;
        document.getElementById('git-no-remote-row').hidden = hasRemote;
        this._editingRemote = false;
    },

    async _saveRemote() {
        const url = document.getElementById('git-remote-url-input')?.value.trim();
        if (!url) { Utils.showToast('Ingresa una URL', 'warning'); return; }
        // Basic URL validation
        if (!url.startsWith('https://') && !url.startsWith('http://') &&
            !url.startsWith('git@') && !url.startsWith('ssh://')) {
            Utils.showToast('URL inválida. Usa https://... o git@...', 'warning');
            return;
        }
        const endpoint = this._editingRemote ? '/api/git/remote/set-url' : '/api/git/remote/add';
        const ok = await this._api('POST', endpoint, { path: this._wsPath, url });
        if (ok) {
            Utils.showToast(this._editingRemote ? 'URL actualizada' : 'Remote añadido', 'success');
            this.refresh();
            if (!this._editingRemote) {
                ExplorerDialog.confirm(
                    '¿Hacer push ahora y publicar la rama en origin?',
                    'Publicar',
                    () => this._pushWithUpstream()
                );
            }
        }
    },

    async _removeRemote() {
        ExplorerDialog.confirm(
            '¿Eliminar el remote "origin"?',
            'Eliminar',
            async () => {
                const ok = await this._api('POST', '/api/git/remote/remove', { path: this._wsPath, name: 'origin' });
                if (ok) {
                    Utils.showToast('Remote eliminado', 'success');
                    this.refresh();
                }
            }
        );
    },

    async _pull() {
        const btn = document.getElementById('git-pull-btn');
        btn.classList.add('spinning');
        const ok = await this._api('POST', '/api/git/pull', { path: this._wsPath });
        if (ok) {
            Utils.showToast('Pull completado', 'success');
            this.refresh();
        }
        btn.classList.remove('spinning');
    },

    // -------------------------------------------------------------------------
    // GitHub create repo
    // -------------------------------------------------------------------------

    _showCreateRepoForm() {
        // Pre-fill repo name from current remote URL or folder name
        const remoteUrl = document.getElementById('git-remote-url')?.textContent || '';
        let repoName = '';
        const match = remoteUrl.match(/\/([^/]+?)(?:\.git)?$/);
        if (match) repoName = match[1];
        if (!repoName && this._wsPath) repoName = this._wsPath.split('/').filter(Boolean).pop() || '';

        document.getElementById('git-gh-repo-name').value = repoName;
        // Restore saved token from localStorage
        document.getElementById('git-gh-token').value = localStorage.getItem('gh_token') || '';
        document.getElementById('git-gh-private').checked = true;
        document.getElementById('git-create-repo-form').hidden = false;
        document.getElementById('git-gh-repo-name').focus();
    },

    _hideCreateRepoForm() {
        document.getElementById('git-create-repo-form').hidden = true;
    },

    async _createGitHubRepo() {
        const name    = document.getElementById('git-gh-repo-name').value.trim();
        const token   = document.getElementById('git-gh-token').value.trim();
        const private_ = document.getElementById('git-gh-private').checked;

        if (!name)  { Utils.showToast('Escribe el nombre del repo', 'warning'); return; }
        if (!token) { Utils.showToast('Se requiere un Personal Access Token de GitHub', 'warning'); return; }

        const saveBtn = document.getElementById('git-create-repo-save');
        saveBtn.disabled = true;
        saveBtn.textContent = 'Creando…';

        const data = await this._api('POST', '/api/github/create-repo', {
            token, name, private: private_, description: '',
        });

        saveBtn.disabled = false;
        saveBtn.textContent = 'Crear en GitHub';

        if (data) {
            // Save token for future use
            localStorage.setItem('gh_token', token);
            Utils.showToast(`Repositorio "${name}" creado`, 'success');
            this._hideCreateRepoForm();

            // Update the remote URL to the new repo
            const cloneUrl = data.clone_url;
            const hasRemote = document.getElementById('git-remote-row')?.hidden === false;
            const endpoint = hasRemote ? '/api/git/remote/set-url' : '/api/git/remote/add';
            const urlOk = await this._api('POST', endpoint, { path: this._wsPath, url: cloneUrl });
            if (urlOk) {
                this.refresh();
                // Push with set-upstream
                ExplorerDialog.confirm(
                    `Repositorio creado en GitHub. ¿Hacer push ahora?`,
                    'Push',
                    () => this._pushWithUpstream()
                );
            }
        }
    },

    // -------------------------------------------------------------------------
    // Activity bar badge
    // -------------------------------------------------------------------------

    _updateActivityBadge(count) {
        const badge = document.getElementById('activity-git-badge');
        if (!badge) return;
        if (count > 0) {
            badge.textContent = count > 99 ? '99+' : String(count);
            badge.hidden = false;
        } else {
            badge.hidden = true;
        }
    },

    // -------------------------------------------------------------------------
    // HTTP helper
    // -------------------------------------------------------------------------

    async _api(method, url, body) {
        try {
            const opts = { method, headers: {} };
            if (body) {
                opts.headers['Content-Type'] = 'application/json';
                opts.body = JSON.stringify(body);
            }
            const res = await fetch(url, opts);
            const data = await res.json();
            if (!res.ok) {
                Utils.showToast(data.detail || 'Error git', 'error');
                return null;
            }
            return data;
        } catch (err) {
            Utils.showToast('Error de red: ' + String(err), 'error');
            return null;
        }
    },
};

window.GitPanel = GitPanel;

// Shorthand helpers local to this file
function enc(s) { return encodeURIComponent(s); }
function esc(s) { return Utils.escapeHtml(String(s ?? '')); }
