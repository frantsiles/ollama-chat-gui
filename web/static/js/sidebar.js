
/**
 * Sidebar/Config module — handles model, temperature, workspace, approval.
 * The panel itself is now controlled by Explorer's activity bar.
 */

const Sidebar = {
    modelSelect: null,
    temperatureSlider: null,
    tempValue: null,
    workspacePath: null,
    approvalLevel: null,
    traceList: null,
    _contextSize: 0,

    init() {
        this.modelSelect     = document.getElementById('model-select');
        this.temperatureSlider = document.getElementById('temperature');
        this.tempValue       = document.getElementById('temp-value');
        this.workspacePath   = document.getElementById('workspace-path');
        this.approvalLevel   = document.getElementById('approval-level');
        this.maxAgentSteps     = document.getElementById('max-agent-steps');
        this.stepsValue        = document.getElementById('steps-value');
        this.agentTaskTimeout  = document.getElementById('agent-task-timeout');
        this.timeoutValue      = document.getElementById('timeout-value');
        this.traceList         = document.getElementById('trace-list');

        this.bindEvents();
        this.loadSettings();
        this.loadModels();

        // Init collapsible config sections
        if (window.Explorer) Explorer.initPanelSections();
    },

    onConnected() {
        if (this.modelSelect.value) {
            this.updateConfig({ model: this.modelSelect.value });
        }
        // Load file tree once we have a session workspace
        this._syncWorkspaceToExplorer();
    },

    _syncWorkspaceToExplorer() {
        if (!wsManager?.sessionId) return;
        const savedWs = () => Utils.storage.get('settings', {}).workspacePath || '';
        fetch(`/api/sessions/${wsManager.sessionId}/config`)
            .then(r => r.json())
            .then(data => {
                const ws = data.workspace_root || savedWs();
                if (ws && window.Explorer) {
                    Explorer.setWorkspace(ws);
                }
                if (ws && this.workspacePath) {
                    this.workspacePath.textContent = Utils.truncatePath(ws, 40);
                }
            })
            .catch(() => {
                const ws = savedWs();
                if (ws && window.Explorer) Explorer.setWorkspace(ws);
                if (ws && this.workspacePath) {
                    this.workspacePath.textContent = Utils.truncatePath(ws, 40);
                }
            });
    },

    bindEvents() {
        // Model
        this.modelSelect.addEventListener('change', (e) => {
            this.updateConfig({ model: e.target.value });
            this.updateModelIndicator(e.target.value);
        });

        // Temperature
        this.temperatureSlider.addEventListener('input', (e) => {
            this.tempValue.textContent = parseFloat(e.target.value).toFixed(1);
        });
        this.temperatureSlider.addEventListener('change', (e) => {
            this.updateConfig({ temperature: parseFloat(e.target.value) });
        });

        // Approval
        this.approvalLevel.addEventListener('change', (e) => {
            this.updateConfig({ approval_level: e.target.value });
        });

        // Max agent steps
        this.maxAgentSteps.addEventListener('input', (e) => {
            if (this.stepsValue) this.stepsValue.textContent = e.target.value;
        });
        this.maxAgentSteps.addEventListener('change', (e) => {
            const val = Math.max(1, Math.min(500, parseInt(e.target.value, 10) || 100));
            e.target.value = val;
            if (this.stepsValue) this.stepsValue.textContent = val;
            this.updateConfig({ max_agent_steps: val });
            this._saveSettings({ maxAgentSteps: val });
        });

        // Agent task timeout
        this.agentTaskTimeout.addEventListener('input', (e) => {
            if (this.timeoutValue) this.timeoutValue.textContent = e.target.value;
        });
        this.agentTaskTimeout.addEventListener('change', (e) => {
            const val = Math.max(30, Math.min(3600, parseInt(e.target.value, 10) || 300));
            e.target.value = val;
            if (this.timeoutValue) this.timeoutValue.textContent = val;
            this.updateConfig({ agent_task_timeout: val });
            this._saveSettings({ agentTaskTimeout: val });
        });

        // Change workspace button (manual path input)
        document.getElementById('change-workspace').addEventListener('click', () => {
            const path = prompt('Ruta del workspace:', this.workspacePath.textContent);
            if (path) {
                this.updateConfig({ workspace_root: path });
                this.workspacePath.textContent = Utils.truncatePath(path, 40);
                if (window.Explorer) Explorer.setWorkspace(path);
            }
        });

        // Explorer toolbar buttons
        const homeBtn = document.getElementById('explorer-nav-home');
        if (homeBtn) {
            homeBtn.addEventListener('click', () => {
                fetch('/api/files').then(r => r.json()).then(data => {
                    // Navigate home
                    const tree = document.getElementById('file-tree');
                    if (tree && window.Explorer) Explorer.navigateTo(data.path);
                }).catch(() => {});
            });
        }

        const refreshBtn = document.getElementById('explorer-refresh');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                if (window.Explorer && Explorer.currentPath) {
                    const tree = document.getElementById('file-tree');
                    tree.innerHTML = '';
                    Explorer._loadTree(Explorer.currentPath, tree, 0);
                }
            });
        }
    },

    async loadModels() {
        Utils.log('SIDEBAR', 'Loading models...');
        try {
            const response = await fetch('/api/models');
            const data = await response.json();

            this.modelSelect.innerHTML = '';

            if (data.models && data.models.length > 0) {
                App.state.modelCapabilities = {};
                data.models.forEach(model => {
                    const option = document.createElement('option');
                    option.value = model.name;
                    option.textContent = model.name;
                    App.state.modelCapabilities[model.name] = model.capabilities || [];

                    // Show capabilities hint
                    if (model.capabilities && model.capabilities.includes('tools')) {
                        option.textContent += ' ⚡';
                        option.title = 'Soporta function calling nativo';
                    }
                    this.modelSelect.appendChild(option);
                });

                const savedModel = Utils.storage.get('selectedModel');
                if (savedModel && data.models.find(m => m.name === savedModel)) {
                    this.modelSelect.value = savedModel;
                } else {
                    this.modelSelect.value = data.models[0].name;
                }

                this.updateModelIndicator(this.modelSelect.value);
                Utils.storage.set('selectedModel', this.modelSelect.value);
                App.state.model = this.modelSelect.value;

                if (wsManager && wsManager.sessionId) {
                    this.updateConfig({ model: this.modelSelect.value });
                }
            } else {
                this.modelSelect.innerHTML = '<option value="">No hay modelos</option>';
            }
        } catch (error) {
            Utils.log('SIDEBAR', 'Error loading models:', error);
            this.modelSelect.innerHTML = '<option value="">Error al cargar</option>';
            Utils.showToast('Error al cargar modelos. ¿Está Ollama corriendo?', 'error');
        }
    },

    loadSettings() {
        const settings = Utils.storage.get('settings', {});

        if (settings.temperature !== undefined) {
            this.temperatureSlider.value = settings.temperature;
            this.tempValue.textContent = Number(settings.temperature).toFixed(1);
        }
        if (settings.approvalLevel) {
            this.approvalLevel.value = settings.approvalLevel;
        }
        if (settings.maxAgentSteps !== undefined) {
            const val = settings.maxAgentSteps;
            this.maxAgentSteps.value = val;
            if (this.stepsValue) this.stepsValue.textContent = val;
        }
        if (settings.agentTaskTimeout !== undefined) {
            const val = settings.agentTaskTimeout;
            this.agentTaskTimeout.value = val;
            if (this.timeoutValue) this.timeoutValue.textContent = val;
        }
        if (settings.workspacePath) {
            this.workspacePath.textContent = Utils.truncatePath(settings.workspacePath, 40);
        }
    },

    async updateConfig(config) {
        if (!wsManager.sessionId) return;
        try {
            const response = await fetch(`/api/sessions/${wsManager.sessionId}/config`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });
            if (response.ok) {
                if (config.model) {
                    Utils.storage.set('selectedModel', config.model);
                    App.state.model = config.model;
                }
                if (config.temperature !== undefined) {
                    this._saveSettings({ temperature: config.temperature });
                }
                if (config.approval_level) {
                    this._saveSettings({ approvalLevel: config.approval_level });
                }
                if (config.max_agent_steps !== undefined) {
                    this.maxAgentSteps.value = config.max_agent_steps;
                    if (this.stepsValue) this.stepsValue.textContent = config.max_agent_steps;
                    this._saveSettings({ maxAgentSteps: config.max_agent_steps });
                }
                if (config.agent_task_timeout !== undefined) {
                    this.agentTaskTimeout.value = config.agent_task_timeout;
                    if (this.timeoutValue) this.timeoutValue.textContent = config.agent_task_timeout;
                    this._saveSettings({ agentTaskTimeout: config.agent_task_timeout });
                }
                if (config.workspace_root) {
                    this._saveSettings({ workspacePath: config.workspace_root });
                }
            }
        } catch (error) {
            console.error('Error updating config:', error);
        }
    },

    _saveSettings(patch) {
        const current = Utils.storage.get('settings', {});
        Utils.storage.set('settings', { ...current, ...patch });
    },

    updateModelIndicator(model) {
        const el = document.getElementById('model-indicator');
        if (el) el.innerHTML = `Modelo: <strong>${model || '-'}</strong>`;
        if (model) this._fetchContextSize(model);
    },

    _fetchContextSize(model) {
        fetch(`/api/models/${encodeURIComponent(model)}/info`)
            .then(r => r.json())
            .then(data => {
                let size = 0;
                const info = data.info || {};
                for (const [key, val] of Object.entries(info.model_info || {})) {
                    if (key.includes('context_length')) { size = parseInt(val) || 0; break; }
                }
                if (!size) {
                    for (const line of (info.parameters || '').split('\n')) {
                        const parts = line.trim().split(/\s+/);
                        if (parts[0] === 'num_ctx' && parts.length >= 2) {
                            size = parseInt(parts[1]) || 0; break;
                        }
                    }
                }
                this._contextSize = size;
                this._refreshContextBar();
            })
            .catch(() => {});
    },

    _refreshContextBar() {
        const fill = document.getElementById('ctx-bar-fill');
        const pct  = document.getElementById('ctx-bar-pct');
        const max  = document.getElementById('ctx-tokens-max');
        if (!fill) return;
        const used = parseInt(document.getElementById('ctx-tokens-used')?.textContent?.replace(/,/g, '') || '0');
        if (this._contextSize > 0 && used > 0) {
            const p = Math.min(100, Math.round(used / this._contextSize * 100));
            fill.style.width = p + '%';
            fill.className = 'ctx-bar-fill' + (p > 80 ? ' danger' : p > 60 ? ' warning' : '');
            if (pct) pct.textContent = p + '%';
            if (max) max.textContent = this._contextSize.toLocaleString();
        } else {
            fill.style.width = '0%';
            if (pct) pct.textContent = '—';
            if (max) max.textContent = this._contextSize > 0 ? this._contextSize.toLocaleString() : '?';
        }
    },

    updateContext(tokenUsage, messageCount) {
        const empty = document.getElementById('ctx-empty');
        const stats = document.getElementById('ctx-stats');
        if (!tokenUsage || !tokenUsage.total_tokens) {
            if (empty) empty.style.display = '';
            if (stats) stats.classList.remove('visible');
            return;
        }
        if (empty) empty.style.display = 'none';
        if (stats) stats.classList.add('visible');

        const fmt = n => Number(n).toLocaleString();
        const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

        set('ctx-msg-count',       messageCount || 0);
        set('ctx-llm-calls',       tokenUsage.calls || 0);
        set('ctx-last-prompt',     fmt(tokenUsage.last_prompt || 0));
        set('ctx-last-completion', fmt(tokenUsage.last_completion || 0));
        set('ctx-total-tokens',    fmt(tokenUsage.total_tokens || 0));
        set('ctx-tokens-used',     fmt(tokenUsage.last_prompt || 0));

        this._refreshContextBar();
    },

    /** Called from websocket/chat handlers with trace array */
    updateTrace(trace) {
        if (!this.traceList) return;
        if (!trace || trace.length === 0) {
            this.traceList.innerHTML = '<div style="padding:8px;color:var(--text-tertiary);font-size:0.75rem">Sin actividad aún</div>';
            return;
        }

        this.traceList.innerHTML = '';
        trace.forEach(item => {
            const el = document.createElement('div');
            el.className = 'trace-item';
            if (item.includes('completado') || item.includes('OK') || item.includes('éxito')) el.classList.add('success');
            else if (item.includes('error') || item.includes('falló')) el.classList.add('error');
            else if (item.includes('esperando') || item.includes('ejecutando')) el.classList.add('pending');
            el.textContent = item;
            this.traceList.appendChild(el);
        });

        this.traceList.scrollTop = this.traceList.scrollHeight;

        // Auto-switch to trace panel when agent is working
        if (window.Explorer) Explorer.setPanel('trace');
        if (window.Explorer) Explorer._expandSidePanel();
    },

    clearTrace() {
        if (this.traceList) this.traceList.innerHTML = '';
    },

    // Kept for backward-compat calls from app.js
    toggle() { if (window.Explorer) Explorer._collapseSidePanel(); },
    open()   { if (window.Explorer) Explorer._expandSidePanel(); },
    close()  { if (window.Explorer) Explorer._collapseSidePanel(); },
};

window.Sidebar = Sidebar;
