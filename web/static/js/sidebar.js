
/**
 * Sidebar module - configuration and controls
 */

const Sidebar = {
    sidebarEl: null,
    toggleBtn: null,
    modelSelect: null,
    temperatureSlider: null,
    tempValue: null,
    workspacePath: null,
    approvalLevel: null,
    traceSection: null,
    traceList: null,

    /**
     * Initialize sidebar module
     */
    init() {
        this.sidebarEl = document.getElementById('sidebar');
        this.toggleBtn = document.getElementById('sidebar-toggle');
        this.modelSelect = document.getElementById('model-select');
        this.temperatureSlider = document.getElementById('temperature');
        this.tempValue = document.getElementById('temp-value');
        this.workspacePath = document.getElementById('workspace-path');
        this.approvalLevel = document.getElementById('approval-level');
        this.traceSection = document.getElementById('trace-section');
        this.traceList = document.getElementById('trace-list');

        this.bindEvents();
        this.loadSettings();
        this.loadModels();
    },

    /**
     * Called after WebSocket connection is established
     */
    onConnected() {
        // Actualizar config del servidor con el modelo actual
        if (this.modelSelect.value) {
            this.updateConfig({ model: this.modelSelect.value });
        }
    },

    /**
     * Bind DOM events
     */
    bindEvents() {
        // Toggle sidebar
        this.toggleBtn.addEventListener('click', () => {
            this.toggle();
        });

        // Model selection
        this.modelSelect.addEventListener('change', (e) => {
            this.updateConfig({ model: e.target.value });
            this.updateModelIndicator(e.target.value);
        });

        // Temperature slider
        this.temperatureSlider.addEventListener('input', (e) => {
            const temp = parseFloat(e.target.value);
            this.tempValue.textContent = temp.toFixed(1);
        });

        this.temperatureSlider.addEventListener('change', (e) => {
            this.updateConfig({ temperature: parseFloat(e.target.value) });
        });

        // Approval level
        this.approvalLevel.addEventListener('change', (e) => {
            this.updateConfig({ approval_level: e.target.value });
        });

        // Change workspace button
        document.getElementById('change-workspace').addEventListener('click', () => {
            const path = prompt('Ingresa la ruta del workspace:', this.workspacePath.textContent);
            if (path) {
                this.updateConfig({ workspace_root: path });
                this.workspacePath.textContent = Utils.truncatePath(path, 40);
            }
        });

        // Close sidebar on mobile when clicking outside
        document.addEventListener('click', (e) => {
            if (window.innerWidth <= 768 && 
                this.sidebarEl.classList.contains('open') &&
                !this.sidebarEl.contains(e.target) &&
                !this.toggleBtn.contains(e.target)) {
                this.close();
            }
        });
    },

    /**
     * Load available models
     */
    async loadModels() {
        Utils.log('SIDEBAR', 'Loading models...');
        try {
            const response = await fetch('/api/models');
            Utils.log('SIDEBAR', 'Models API response:', response.status);
            const data = await response.json();
            Utils.log('SIDEBAR', 'Models data:', data);
            
            this.modelSelect.innerHTML = '';
            
            if (data.models && data.models.length > 0) {
                data.models.forEach(model => {
                    const option = document.createElement('option');
                    option.value = model.name;
                    option.textContent = model.name;
                    this.modelSelect.appendChild(option);
                });

                // Select first model if none selected
                const savedModel = Utils.storage.get('selectedModel');
                if (savedModel && data.models.find(m => m.name === savedModel)) {
                    this.modelSelect.value = savedModel;
                } else {
                    this.modelSelect.value = data.models[0].name;
                }
                
                this.updateModelIndicator(this.modelSelect.value);
                Utils.storage.set('selectedModel', this.modelSelect.value);
                App.state.model = this.modelSelect.value;
                Utils.log('SIDEBAR', 'Model selected:', this.modelSelect.value);

                // Si ya hay sesión WS, sincronizar modelo al backend inmediatamente
                if (wsManager && wsManager.sessionId) {
                    this.updateConfig({ model: this.modelSelect.value });
                }
            } else {
                this.modelSelect.innerHTML = '<option value="">No hay modelos</option>';
                Utils.log('SIDEBAR', 'No models available');
            }
        } catch (error) {
            Utils.log('SIDEBAR', '❌ Error loading models:', error);
            this.modelSelect.innerHTML = '<option value="">Error al cargar</option>';
            Utils.showToast('Error al cargar modelos. ¿Está Ollama corriendo?', 'error');
        }
    },

    /**
     * Load saved settings
     */
    loadSettings() {
        const settings = Utils.storage.get('settings', {});
        
        if (settings.temperature !== undefined) {
            this.temperatureSlider.value = settings.temperature;
            this.tempValue.textContent = settings.temperature.toFixed(1);
        }

        if (settings.approvalLevel) {
            this.approvalLevel.value = settings.approvalLevel;
        }

        if (settings.workspacePath) {
            this.workspacePath.textContent = Utils.truncatePath(settings.workspacePath, 40);
        }
    },

    /**
     * Save settings locally
     */
    saveSettings(settings) {
        const current = Utils.storage.get('settings', {});
        Utils.storage.set('settings', { ...current, ...settings });
    },

    /**
     * Update configuration on server
     */
    async updateConfig(config) {
        if (!wsManager.sessionId) return;

        try {
            const response = await fetch(`/api/sessions/${wsManager.sessionId}/config`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });

            if (response.ok) {
                // Save locally too
                if (config.model) {
                    Utils.storage.set('selectedModel', config.model);
                    App.state.model = config.model;
                }
                if (config.temperature !== undefined) {
                    this.saveSettings({ temperature: config.temperature });
                }
                if (config.approval_level) {
                    this.saveSettings({ approvalLevel: config.approval_level });
                }
                if (config.workspace_root) {
                    this.saveSettings({ workspacePath: config.workspace_root });
                }
            }
        } catch (error) {
            console.error('Error updating config:', error);
        }
    },

    /**
     * Update model indicator in footer
     */
    updateModelIndicator(model) {
        const indicator = document.getElementById('model-indicator');
        if (indicator) {
            indicator.innerHTML = `Modelo: <strong>${model || '-'}</strong>`;
        }
    },

    /**
     * Update trace display
     */
    updateTrace(trace) {
        if (!trace || trace.length === 0) {
            this.traceSection.style.display = 'none';
            return;
        }

        this.traceSection.style.display = 'block';
        this.traceList.innerHTML = '';

        trace.forEach(item => {
            const traceItem = document.createElement('div');
            traceItem.className = 'trace-item';
            
            // Add status class based on content
            if (item.includes('completado') || item.includes('OK')) {
                traceItem.classList.add('success');
            } else if (item.includes('error') || item.includes('falló')) {
                traceItem.classList.add('error');
            } else if (item.includes('esperando') || item.includes('ejecutando')) {
                traceItem.classList.add('pending');
            }
            
            traceItem.textContent = item;
            this.traceList.appendChild(traceItem);
        });

        // Scroll to latest
        this.traceList.scrollTop = this.traceList.scrollHeight;
    },

    /**
     * Clear trace
     */
    clearTrace() {
        this.traceList.innerHTML = '';
        this.traceSection.style.display = 'none';
    },

    /**
     * Toggle sidebar
     */
    toggle() {
        if (window.innerWidth <= 768) {
            this.sidebarEl.classList.toggle('open');
        } else {
            this.sidebarEl.classList.toggle('collapsed');
        }
    },

    /**
     * Open sidebar
     */
    open() {
        if (window.innerWidth <= 768) {
            this.sidebarEl.classList.add('open');
        } else {
            this.sidebarEl.classList.remove('collapsed');
        }
    },

    /**
     * Close sidebar
     */
    close() {
        if (window.innerWidth <= 768) {
            this.sidebarEl.classList.remove('open');
        } else {
            this.sidebarEl.classList.add('collapsed');
        }
    }
};

// Make available globally
window.Sidebar = Sidebar;
