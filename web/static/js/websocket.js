
/**
 * WebSocket connection manager
 */

class WebSocketManager {
    constructor() {
        this.ws = null;
        this.sessionId = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000;
        this.handlers = {};
        this.pingInterval = null;
        this.isConnecting = false;
    }

    /**
     * Connect to WebSocket server
     */
    connect(sessionId = null) {
        Utils.log('WS', 'connect() called', { sessionId, currentState: this.ws?.readyState });
        
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            Utils.log('WS', 'Already connected, returning');
            return Promise.resolve();
        }

        if (this.isConnecting) {
            Utils.log('WS', 'Already connecting, waiting...');
            return new Promise((resolve) => {
                const checkConnection = setInterval(() => {
                    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                        clearInterval(checkConnection);
                        resolve();
                    }
                }, 100);
            });
        }

        this.isConnecting = true;
        this.sessionId = sessionId || Utils.storage.get('sessionId') || Utils.generateId();
        Utils.storage.set('sessionId', this.sessionId);
        Utils.log('WS', 'Session ID:', this.sessionId);

        return new Promise((resolve, reject) => {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/${this.sessionId}`;
            
            Utils.log('WS', '🔌 Connecting to:', wsUrl);
            this.updateConnectionStatus('connecting');
            
            try {
                this.ws = new WebSocket(wsUrl);
                Utils.log('WS', 'WebSocket object created');
            } catch (error) {
                Utils.log('WS', '❌ WebSocket creation failed:', error);
                this.isConnecting = false;
                reject(error);
                return;
            }

            this.ws.onopen = () => {
                Utils.log('WS', '✅ Connection opened');
                this.isConnecting = false;
                this.reconnectAttempts = 0;
                this.updateConnectionStatus('connected');
                this.startPing();
                resolve();
            };

            this.ws.onclose = (event) => {
                Utils.log('WS', '🔴 Connection closed', { code: event.code, reason: event.reason, wasClean: event.wasClean });
                this.isConnecting = false;
                this.stopPing();
                this.updateConnectionStatus('disconnected');
                
                if (!event.wasClean && this.reconnectAttempts < this.maxReconnectAttempts) {
                    this.scheduleReconnect();
                }
            };

            this.ws.onerror = (error) => {
                Utils.log('WS', '❌ Connection error', error);
                this.isConnecting = false;
                this.updateConnectionStatus('disconnected');
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                } catch (error) {
                    console.error('Error parsing message:', error);
                }
            };

            // Timeout for connection
            setTimeout(() => {
                if (this.isConnecting) {
                    this.isConnecting = false;
                    this.ws.close();
                    reject(new Error('Connection timeout'));
                }
            }, 10000);
        });
    }

    /**
     * Disconnect from WebSocket server
     */
    disconnect() {
        this.stopPing();
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }

    /**
     * Send message through WebSocket
     */
    send(data) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            console.error('WebSocket not connected');
            return false;
        }

        try {
            this.ws.send(JSON.stringify(data));
            return true;
        } catch (error) {
            console.error('Error sending message:', error);
            return false;
        }
    }

    /**
     * Send chat message
     */
    sendChat(content, attachments = [], images = [], imageNames = []) {
        return this.send({
            type: 'chat',
            content,
            attachments,
            images,
            image_names: imageNames
        });
    }

    /**
     * Send streaming chat message
     */
    sendStreamChat(content) {
        return this.send({
            type: 'stream_chat',
            content
        });
    }

    /**
     * Send approval response
     */
    sendApproval(approved) {
        return this.send({
            type: 'approval',
            approved
        });
    }

    /**
     * Send plan action
     */
    sendPlanAction(action) {
        return this.send({
            type: 'plan',
            action
        });
    }

    /**
     * Send cancel request
     */
    sendCancel() {
        return this.send({ type: 'cancel' });
    }

    /**
     * Register event handler
     */
    on(event, handler) {
        if (!this.handlers[event]) {
            this.handlers[event] = [];
        }
        this.handlers[event].push(handler);
    }

    /**
     * Remove event handler
     */
    off(event, handler) {
        if (this.handlers[event]) {
            this.handlers[event] = this.handlers[event].filter(h => h !== handler);
        }
    }

    /**
     * Handle incoming message
     */
    handleMessage(data) {
        const { type, ...payload } = data;
        
        // Call registered handlers
        if (this.handlers[type]) {
            this.handlers[type].forEach(handler => handler(payload));
        }
        
        // Call generic message handlers
        if (this.handlers['message']) {
            this.handlers['message'].forEach(handler => handler(data));
        }
    }

    /**
     * Update connection status UI
     */
    updateConnectionStatus(status) {
        const statusEl = document.getElementById('connection-status');
        if (!statusEl) return;

        const dot = statusEl.querySelector('.status-dot');
        const text = statusEl.querySelector('.status-text');

        if (dot) {
            dot.className = 'status-dot ' + status;
        }

        if (text) {
            const statusTexts = {
                connected: 'Conectado',
                disconnected: 'Desconectado',
                connecting: 'Conectando...'
            };
            text.textContent = statusTexts[status] || status;
        }

        // Emit status change event
        if (this.handlers['connectionChange']) {
            this.handlers['connectionChange'].forEach(handler => handler(status));
        }
    }

    /**
     * Schedule reconnection attempt
     */
    scheduleReconnect() {
        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
        
        console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
        
        setTimeout(() => {
            this.connect(this.sessionId).catch(() => {
                if (this.reconnectAttempts < this.maxReconnectAttempts) {
                    this.scheduleReconnect();
                }
            });
        }, delay);
    }

    /**
     * Start ping interval to keep connection alive
     */
    startPing() {
        this.stopPing();
        this.pingInterval = setInterval(() => {
            this.send({ type: 'ping' });
        }, 30000);
    }

    /**
     * Stop ping interval
     */
    stopPing() {
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
    }

    /**
     * Check if connected
     */
    get isConnected() {
        return this.ws && this.ws.readyState === WebSocket.OPEN;
    }
}

// Create global instance
window.wsManager = new WebSocketManager();
