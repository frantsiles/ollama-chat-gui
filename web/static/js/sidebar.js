
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
                data.models.forEach(model => {
                    const option = document.createElement('option');
                    option.value = model.name;
                    option.textContent = model.name;

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
