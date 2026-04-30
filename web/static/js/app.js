
/**
 * Main application module - orchestrates all modules
 */

const App = {
    state: {
        mode: 'agent',
        model: '',
        sessionId: null,
        isConnected: false,
        modelCapabilities: {}
    },

    /**
     * Initialize the application
     */
    async init() {
        Utils.log('APP', '🚀 Initializing Ollama Chat...');

        // Initialize theme
        try {
            this.initTheme();
            Utils.log('APP', 'Theme initialized');
        } catch (error) {
            Utils.log('APP', 'Theme init error:', error);
        }

        // Setup connection status handler early
        if (window.wsManager && typeof wsManager.on === 'function') {
            wsManager.on('connectionChange', (status) => {
                Utils.log('APP', 'Connection status changed:', status);
                this.state.isConnected = status === 'connected';
                if (window.Chat && typeof Chat.onConnectionChange === 'function') {
                    Chat.onConnectionChange(status);
                }
            });
        }

        // Initialize all modules (defensive)
        Utils.log('APP', 'Initializing modules...');
        this.safeInitModule('Explorer', window.Explorer);
        this.safeInitModule('FileViewer', window.FileViewer);
        this.safeInitModule('QuickOpen', window.QuickOpen);
        this.safeInitModule('SearchPanel', window.SearchPanel);
        this.safeInitModule('Breadcrumbs', window.Breadcrumbs);
        this.safeInitModule('TreeSelection', window.TreeSelection);
        this.safeInitModule('GitStatus', window.GitStatus);
        this.safeInitModule('GitPanel', window.GitPanel);
        this.safeInitModule('FileWatcher', window.FileWatcher);
        this.safeInitModule('Sidebar', window.Sidebar);
        this.safeInitModule('Plan', window.Plan);
        this.safeInitModule('Modes', window.Modes);
        this.safeInitModule('Skills', window.Skills);
        this.safeInitModule('History', window.History);
        this.safeInitModule('Shortcuts', window.Shortcuts);
        this.safeInitModule('Chat', window.Chat);
        this.safeInitModule('MCP', window.MCP);
        Utils.log('APP', 'Module initialization finished');

        // Connect to WebSocket
        Utils.log('APP', 'Starting WebSocket connection...');
        try {
            await wsManager.connect();
            this.state.isConnected = true;
            this.state.sessionId = wsManager.sessionId;
            Utils.log('APP', '✅ Connected! Session:', wsManager.sessionId);
            // Ahora actualizar config del servidor con el modelo actual
            if (window.Sidebar && typeof Sidebar.onConnected === 'function') {
                Sidebar.onConnected();
            }
            // Actualizar estado del botón enviar
            if (window.Chat && typeof Chat.updateSendButton === 'function') {
                Chat.updateSendButton();
            }
            // Cargar historial de conversaciones
            if (window.History && typeof History.load === 'function') {
                History.load();
            }
        } catch (error) {
            Utils.log('APP', '❌ Connection failed:', error);
            Utils.showToast('Error de conexión. Reintentando...', 'error');
        }

        // Focus input
        const input = document.getElementById('message-input');
        if (input) {
            input.focus();
        }

        Utils.log('APP', '✅ App initialization complete');
    },

    /**
     * Safely initialize a module without blocking app startup
     */
    safeInitModule(name, moduleObj) {
        if (!moduleObj || typeof moduleObj.init !== 'function') {
            Utils.log('APP', `${name} module unavailable or invalid`);
            return;
        }
        try {
            moduleObj.init();
            Utils.log('APP', `${name} initialized`);
        } catch (error) {
            Utils.log('APP', `${name} init error:`, error);
        }
    },

    /**
     * Initialize theme from saved preference
     */
    initTheme() {
        const savedTheme = Utils.storage.get('theme', 'dark');
        document.documentElement.setAttribute('data-theme', savedTheme);

        // Theme toggle button
        document.getElementById('theme-toggle').addEventListener('click', () => {
            this.toggleTheme();
        });
    },

    /**
     * Toggle between light and dark theme
     */
    toggleTheme() {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

        document.documentElement.setAttribute('data-theme', newTheme);
        Utils.storage.set('theme', newTheme);

        if (window.FileViewer) FileViewer._syncTheme();
    },

    /**
     * Get current theme
     */
    getTheme() {
        return document.documentElement.getAttribute('data-theme') || 'dark';
    }
};

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    App.init().catch((error) => {
        console.error('Fatal app initialization error:', error);
        Utils.showToast('Error inicializando la aplicación', 'error');
    });
});

// Handle visibility change (reconnect when tab becomes visible)
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && !wsManager.isConnected) {
        wsManager.connect().catch(console.error);
    }
});

// Handle beforeunload
window.addEventListener('beforeunload', () => {
    wsManager.disconnect();
});

// Make available globally
window.App = App;
