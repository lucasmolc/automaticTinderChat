/**
 * WebSocket client para notificações em tempo real.
 * Conecta automaticamente ao servidor SocketIO e gerencia eventos.
 */

class WebSocketClient {
    constructor() {
        this.socket = null;
        this.isConnected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000;
        this.callbacks = {};
        this.subscribedRooms = new Set();
    }

    /**
     * Inicializa conexão WebSocket
     */
    connect() {
        // Verificar se SocketIO está disponível
        if (typeof io === 'undefined') {
            console.warn('SocketIO não disponível. Usando polling.');
            this.startPolling();
            return;
        }

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        
        try {
            this.socket = io({
                transports: ['websocket', 'polling'],
                reconnection: true,
                reconnectionAttempts: this.maxReconnectAttempts,
                reconnectionDelay: this.reconnectDelay
            });

            this.setupEventHandlers();
            console.log('🔌 WebSocket: Conectando...');
        } catch (error) {
            console.error('Erro ao conectar WebSocket:', error);
            this.startPolling();
        }
    }

    /**
     * Configura handlers de eventos WebSocket
     */
    setupEventHandlers() {
        this.socket.on('connect', () => {
            console.log('✅ WebSocket: Conectado');
            this.isConnected = true;
            this.reconnectAttempts = 0;
            
            // Reinscrever em rooms
            this.subscribedRooms.forEach(room => {
                this.socket.emit('subscribe', { room });
            });

            // Auto-subscribe em rooms padrão
            this.subscribe('notifications');
            this.subscribe('stats');

            // Callback de conexão
            this.emit('connected');
        });

        this.socket.on('disconnect', (reason) => {
            console.log('❌ WebSocket: Desconectado -', reason);
            this.isConnected = false;
            this.emit('disconnected', { reason });
        });

        this.socket.on('connect_error', (error) => {
            console.error('WebSocket: Erro de conexão', error);
            this.reconnectAttempts++;
            
            if (this.reconnectAttempts >= this.maxReconnectAttempts) {
                console.log('WebSocket: Máximo de tentativas. Usando polling.');
                this.startPolling();
            }
        });

        // Eventos customizados
        this.socket.on('notification', (data) => {
            console.log('📬 Notificação recebida:', data);
            this.emit('notification', data);
            this.showNotification(data);
        });

        this.socket.on('stats_update', (data) => {
            console.log('📊 Stats atualizadas:', data);
            this.emit('stats_update', data);
        });

        this.socket.on('automation_status', (data) => {
            console.log('🤖 Status automação:', data);
            this.emit('automation_status', data);
        });

        this.socket.on('match_update', (data) => {
            console.log('💕 Match atualizado:', data);
            this.emit('match_update', data);
        });

        this.socket.on('pong', () => {
            console.log('🏓 Pong recebido');
        });
    }

    /**
     * Inscreve em um room específico
     */
    subscribe(room) {
        if (this.socket && this.isConnected) {
            this.socket.emit('subscribe', { room });
            this.subscribedRooms.add(room);
            console.log(`📥 Inscrito em: ${room}`);
        }
    }

    /**
     * Cancela inscrição de um room
     */
    unsubscribe(room) {
        if (this.socket && this.isConnected) {
            this.socket.emit('unsubscribe', { room });
            this.subscribedRooms.delete(room);
            console.log(`📤 Desinscrito de: ${room}`);
        }
    }

    /**
     * Inscreve em atualizações de um match específico
     */
    subscribeToMatch(matchId) {
        this.subscribe(`match:${matchId}`);
    }

    /**
     * Registra callback para evento
     */
    on(event, callback) {
        if (!this.callbacks[event]) {
            this.callbacks[event] = [];
        }
        this.callbacks[event].push(callback);
    }

    /**
     * Remove callback de evento
     */
    off(event, callback) {
        if (this.callbacks[event]) {
            this.callbacks[event] = this.callbacks[event].filter(cb => cb !== callback);
        }
    }

    /**
     * Emite evento para callbacks registrados
     */
    emit(event, data = {}) {
        if (this.callbacks[event]) {
            this.callbacks[event].forEach(callback => {
                try {
                    callback(data);
                } catch (error) {
                    console.error(`Erro em callback de ${event}:`, error);
                }
            });
        }
    }

    /**
     * Exibe notificação visual
     */
    showNotification(data) {
        // Verificar se browser notifications estão habilitadas
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification(data.title || 'Nova Notificação', {
                body: data.message,
                icon: '/static/icon.png',
                tag: data.id
            });
        }

        // Atualizar badge de notificações no header
        this.updateNotificationBadge();
    }

    /**
     * Atualiza badge de notificações
     */
    updateNotificationBadge() {
        const badge = document.querySelector('.notification-badge');
        if (badge) {
            const count = parseInt(badge.textContent) || 0;
            badge.textContent = count + 1;
            badge.style.display = 'flex';
        }
    }

    /**
     * Envia ping para verificar conexão
     */
    ping() {
        if (this.socket && this.isConnected) {
            this.socket.emit('ping');
        }
    }

    /**
     * Fallback para polling quando WebSocket não disponível
     */
    startPolling() {
        console.log('📡 Iniciando modo polling...');
        
        // Polling de notificações a cada 5 segundos
        setInterval(() => {
            this.pollNotifications();
        }, 5000);

        // Polling de stats a cada 10 segundos
        setInterval(() => {
            this.pollStats();
        }, 10000);
    }

    /**
     * Polling de notificações
     */
    async pollNotifications() {
        try {
            const response = await fetch('/api/notifications?unread=true');
            const data = await response.json();
            
            if (data.success && data.notifications && data.notifications.length > 0) {
                data.notifications.forEach(notification => {
                    this.emit('notification', notification);
                });
            }
        } catch (error) {
            console.error('Erro no polling de notificações:', error);
        }
    }

    /**
     * Polling de stats
     */
    async pollStats() {
        try {
            const response = await fetch('/api/stats');
            const data = await response.json();
            
            if (data.success) {
                this.emit('stats_update', data.data);
            }
        } catch (error) {
            console.error('Erro no polling de stats:', error);
        }
    }

    /**
     * Desconecta WebSocket
     */
    disconnect() {
        if (this.socket) {
            this.socket.disconnect();
            this.socket = null;
            this.isConnected = false;
        }
    }
}

// Instância global
const wsClient = new WebSocketClient();

// Auto-connect quando DOM carregado
document.addEventListener('DOMContentLoaded', () => {
    wsClient.connect();

    // Solicitar permissão para notificações do browser
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
});

// Exportar para uso global
window.wsClient = wsClient;
