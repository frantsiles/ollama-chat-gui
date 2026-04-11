
/**
 * Modes module - Chat, Agent, Plan mode selection
 */

const Modes = {
    selectorEl: null,
    buttons: null,
    currentMode: 'agent',

    /**
     * Initialize modes module
     */
    init() {
        this.selectorEl = document.getElementById('mode-selector');
        this.buttons = this.selectorEl.querySelectorAll('.mode-btn');
        
        this.bindEvents();
        this.loadSavedMode();
    },

    /**
     * Bind DOM events
     */
    bindEvents() {
        this.buttons.forEach(btn => {
            btn.addEventListener('click', () => {
                const mode = btn.dataset.mode;
                this.setMode(mode);
            });
        });
    },

    /**
     * Load saved mode from storage
     */
    loadSavedMode() {
        const savedMode = Utils.storage.get('mode', 'agent');
        this.setMode(savedMode, false);
    },

    /**
     * Set the current mode
     */
    setMode(mode, save = true) {
        if (!['chat', 'agent', 'plan'].includes(mode)) return;

        this.currentMode = mode;

        // Update UI
        this.buttons.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });

        // Update mode indicator
        this.updateModeIndicator(mode);

        // Save preference
        if (save) {
            Utils.storage.set('mode', mode);
        }

        // Update app state
        App.state.mode = mode;

        // Update server config
        this.updateServerConfig(mode);

        // Close plan panel if switching away from plan mode
        if (mode !== 'plan') {
            Plan.hide();
        }

        // Clear trace when switching modes
        Sidebar.clearTrace();
    },

    /**
     * Update mode indicator in footer
     */
    updateModeIndicator(mode) {
        const indicator = document.getElementById('mode-indicator');
        if (!indicator) return;

        const modeNames = {
            chat: 'Chat',
            agent: 'Agent',
            plan: 'Plan'
        };

        indicator.innerHTML = `Modo: <strong>${modeNames[mode] || mode}</strong>`;
    },

    /**
     * Update server configuration
     */
    async updateServerConfig(mode) {
        if (!wsManager.sessionId) return;

        try {
            await fetch(`/api/sessions/${wsManager.sessionId}/config`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode })
            });
        } catch (error) {
            console.error('Error updating mode:', error);
        }
    },

    /**
     * Get current mode
     */
    getMode() {
        return this.currentMode;
    },

    /**
     * Check if current mode is chat
     */
    isChat() {
        return this.currentMode === 'chat';
    },

    /**
     * Check if current mode is agent
     */
    isAgent() {
        return this.currentMode === 'agent';
    },

    /**
     * Check if current mode is plan
     */
    isPlan() {
        return this.currentMode === 'plan';
    }
};

// Make available globally
window.Modes = Modes;
