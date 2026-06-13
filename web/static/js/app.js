/* App JS: notificações, integração WebSocket, toasts e modais.
   Extraído de base.html. Carrega após bootstrap.bundle e websocket.js. */

        // Toggle sidebar on mobile
        function toggleSidebar() {
            document.getElementById('sidebar').classList.toggle('show');
        }
        
        // Close sidebar when clicking outside on mobile
        document.addEventListener('click', function(e) {
            const sidebar = document.getElementById('sidebar');
            const toggle = document.querySelector('.mobile-toggle');
            if (window.innerWidth < 992 && 
                !sidebar.contains(e.target) && 
                !toggle.contains(e.target) &&
                sidebar.classList.contains('show')) {
                sidebar.classList.remove('show');
            }
        });
        
        // Format date helper
        function formatDate(dateStr) {
            if (!dateStr) return '-';
            const date = new Date(dateStr);
            return date.toLocaleDateString('pt-BR', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        }
        
        // Format relative time
        function formatRelativeTime(dateStr) {
            if (!dateStr) return '-';
            const date = new Date(dateStr);
            const now = new Date();
            const diff = now - date;
            
            const minutes = Math.floor(diff / 60000);
            const hours = Math.floor(diff / 3600000);
            const days = Math.floor(diff / 86400000);
            
            if (minutes < 1) return 'Agora';
            if (minutes < 60) return `${minutes}m atrás`;
            if (hours < 24) return `${hours}h atrás`;
            if (days < 7) return `${days}d atrás`;
            return formatDate(dateStr);
        }
        
        // ==================== NOTIFICATION SYSTEM ====================
        
        let notificationsOpen = false;
        let lastNotificationCount = 0;
        
        // Toggle notification dropdown
        function toggleNotifications() {
            const dropdown = document.getElementById('notificationDropdown');
            notificationsOpen = !notificationsOpen;
            
            if (notificationsOpen) {
                dropdown.classList.add('show');
                loadNotifications();
            } else {
                dropdown.classList.remove('show');
            }
        }
        
        // Close dropdown when clicking outside
        document.addEventListener('click', function(e) {
            const bell = document.getElementById('notificationBell');
            const dropdown = document.getElementById('notificationDropdown');
            
            if (bell && dropdown && notificationsOpen && 
                !bell.contains(e.target) && !dropdown.contains(e.target)) {
                dropdown.classList.remove('show');
                notificationsOpen = false;
            }
        });
        
        // Load notifications
        async function loadNotifications() {
            try {
                const response = await fetch('/api/notifications?limit=20');
                const data = await response.json();
                
                if (data.success) {
                    renderNotifications(data.data);
                    updateNotificationBadge(data.unread_count);
                }
            } catch (error) {
                console.error('Error loading notifications:', error);
            }
        }
        
        // Render notifications
        function renderNotifications(notifications) {
            const list = document.getElementById('notificationList');
            
            if (!notifications || notifications.length === 0) {
                list.innerHTML = `
                    <div class="notification-empty">
                        <i class="bi bi-bell-slash"></i>
                        <p class="mb-0">Nenhuma notificação</p>
                    </div>
                `;
                return;
            }
            
            list.innerHTML = notifications.map(n => `
                <div class="notification-item ${n.read ? '' : 'unread'}" 
                     onclick="handleNotificationClick('${n.id}', ${n.match_id || 'null'})"
                     style="position: relative;">
                    <div class="notification-icon ${n.color}">
                        ${n.icon}
                    </div>
                    <div class="notification-content">
                        <div class="notification-title">${n.title}</div>
                        <div class="notification-message">${n.message}</div>
                        <div class="notification-time">${n.timestamp}</div>
                    </div>
                    <button class="btn btn-sm text-muted p-1" 
                            onclick="event.stopPropagation(); deleteNotification('${n.id}')"
                            style="position: absolute; top: 0.5rem; right: 0.5rem; opacity: 0.5;">
                        <i class="bi bi-x"></i>
                    </button>
                </div>
            `).join('');
        }
        
        // Update notification badge
        function updateNotificationBadge(count) {
            const badge = document.getElementById('notificationBadge');
            const bell = document.getElementById('notificationBell');
            
            if (count > 0) {
                badge.textContent = count > 99 ? '99+' : count;
                badge.style.display = 'flex';
                bell.querySelector('i').classList.add('text-warning');
                
                // Play sound if new notifications
                if (count > lastNotificationCount && lastNotificationCount > 0) {
                    playNotificationSound();
                }
            } else {
                badge.style.display = 'none';
                bell.querySelector('i').classList.remove('text-warning');
            }
            
            lastNotificationCount = count;
        }
        
        // Play notification sound
        function playNotificationSound() {
            // Simple beep using Web Audio API
            try {
                const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                const oscillator = audioCtx.createOscillator();
                const gainNode = audioCtx.createGain();
                
                oscillator.connect(gainNode);
                gainNode.connect(audioCtx.destination);
                
                oscillator.frequency.value = 800;
                oscillator.type = 'sine';
                gainNode.gain.value = 0.1;
                
                oscillator.start();
                oscillator.stop(audioCtx.currentTime + 0.1);
            } catch (e) {
                // Audio not available
            }
        }
        
        // Handle notification click
        async function handleNotificationClick(notificationId, matchId) {
            // Mark as read
            await fetch(`/api/notifications/${notificationId}/read`, { method: 'POST' });
            
            // Navigate to match if applicable
            if (matchId) {
                window.location.href = `/matches?highlight=${matchId}`;
            }
            
            loadNotifications();
        }
        
        // Mark all as read
        async function markAllAsRead() {
            try {
                await fetch('/api/notifications/read-all', { method: 'POST' });
                loadNotifications();
            } catch (error) {
                console.error('Error marking all as read:', error);
            }
        }
        
        // Delete notification
        async function deleteNotification(notificationId) {
            try {
                await fetch(`/api/notifications/${notificationId}`, { method: 'DELETE' });
                loadNotifications();
            } catch (error) {
                console.error('Error deleting notification:', error);
            }
        }
        
        // Clear all notifications
        async function clearAllNotifications() {
            try {
                await fetch('/api/notifications/clear', { method: 'POST' });
                loadNotifications();
            } catch (error) {
                console.error('Error clearing notifications:', error);
            }
        }
        
        // Poll for new notifications every 30 seconds
        function startNotificationPolling() {
            // Initial load
            checkNotificationCount();
            
            // Poll every 30 seconds
            setInterval(checkNotificationCount, 30000);
        }
        
        // Check notification count (lightweight)
        async function checkNotificationCount() {
            try {
                const response = await fetch('/api/notifications/count');
                const data = await response.json();
                
                if (data.success) {
                    updateNotificationBadge(data.unread_count);
                }
            } catch (error) {
                // Silent fail
            }
        }
        
        // Start polling when page loads
        document.addEventListener('DOMContentLoaded', startNotificationPolling);

        // Integração WebSocket com a página
        document.addEventListener('DOMContentLoaded', function() {
            if (window.wsClient) {
                // Atualizar stats em tempo real
                wsClient.on('stats_update', function(data) {
                    // Atualizar cards de estatísticas se existirem
                    if (data.total_matches && document.getElementById('stat-matches')) {
                        document.getElementById('stat-matches').textContent = data.total_matches;
                    }
                    if (data.total_messages && document.getElementById('stat-messages')) {
                        document.getElementById('stat-messages').textContent = data.total_messages;
                    }
                });
                
                // Atualizar status da automação
                wsClient.on('automation_status', function(data) {
                    const statusBadge = document.getElementById('automation-status-badge');
                    if (statusBadge) {
                        if (data.is_running) {
                            statusBadge.className = 'badge bg-success';
                            statusBadge.textContent = 'Rodando';
                        } else {
                            statusBadge.className = 'badge bg-secondary';
                            statusBadge.textContent = 'Parado';
                        }
                    }
                });
                
                // Notificações em tempo real
                wsClient.on('notification', function(data) {
                    // Toast de notificação
                    showToast(data.type || 'info', data.message || 'Nova notificação');
                    
                    // Atualizar dropdown de notificações se aberto
                    if (typeof loadNotifications === 'function') {
                        loadNotifications();
                    }
                });
            }
        });
        
        // Toast helper
        function showToast(type, message) {
            const toastContainer = document.getElementById('toast-container');
            if (!toastContainer) {
                const container = document.createElement('div');
                container.id = 'toast-container';
                container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
                container.style.zIndex = '1100';
                document.body.appendChild(container);
            }
            
            const toastId = 'toast-' + Date.now();
            const iconMap = {
                'success': 'bi-check-circle-fill text-success',
                'error': 'bi-exclamation-triangle-fill text-danger',
                'warning': 'bi-exclamation-circle-fill text-warning',
                'info': 'bi-info-circle-fill text-info',
                'new_match': 'bi-heart-fill text-danger',
                'new_message': 'bi-chat-fill text-primary'
            };
            
            const icon = iconMap[type] || iconMap['info'];
            
            const toastHtml = `
                <div id="${toastId}" class="toast" role="alert">
                    <div class="toast-header bg-dark">
                        <i class="bi ${icon} me-2"></i>
                        <strong class="me-auto">Notificação</strong>
                        <small>agora</small>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast"></button>
                    </div>
                    <div class="toast-body bg-dark text-light">
                        ${message}
                    </div>
                </div>
            `;
            
            document.getElementById('toast-container').insertAdjacentHTML('beforeend', toastHtml);
            const toastElement = document.getElementById(toastId);
            const toast = new bootstrap.Toast(toastElement, { delay: 5000 });
            toast.show();
            
            toastElement.addEventListener('hidden.bs.toast', () => toastElement.remove());
        }

    /**
     * Sistema de Modais Customizados
     * Substitui confirm(), alert() e prompt() nativos do navegador
     * 
     * Uso:
     *   // Confirmação simples
     *   const confirmed = await customConfirm('Deseja continuar?');
     *   
     *   // Com título e tipo
     *   const confirmed = await customConfirm({
     *       title: 'Iniciar Automação',
     *       message: 'Isso irá enviar mensagens automaticamente.',
     *       type: 'warning',
     *       confirmText: 'Iniciar',
     *       cancelText: 'Voltar'
     *   });
     *   
     *   // Alert customizado
     *   await customAlert('Operação concluída!', 'success');
     *   await customAlert({ title: 'Erro', message: 'Algo deu errado', type: 'danger' });
     */
    
    const CustomModal = {
        overlay: null,
        iconEl: null,
        iconI: null,
        titleEl: null,
        messageEl: null,
        cancelBtn: null,
        confirmBtn: null,
        resolveCallback: null,
        
        // Configurações de ícones e cores por tipo
        typeConfig: {
            confirm: { icon: 'bi-question-circle', color: 'confirm' },
            warning: { icon: 'bi-exclamation-triangle', color: 'warning' },
            danger: { icon: 'bi-x-octagon', color: 'danger' },
            success: { icon: 'bi-check-circle', color: 'success' },
            info: { icon: 'bi-info-circle', color: 'info' }
        },
        
        init() {
            this.overlay = document.getElementById('customModalOverlay');
            this.iconEl = document.getElementById('customModalIcon');
            this.iconI = document.getElementById('customModalIconI');
            this.titleEl = document.getElementById('customModalTitle');
            this.messageEl = document.getElementById('customModalMessage');
            this.cancelBtn = document.getElementById('customModalCancel');
            this.confirmBtn = document.getElementById('customModalConfirm');
            
            // Event listeners
            this.cancelBtn.addEventListener('click', () => this.close(false));
            this.confirmBtn.addEventListener('click', () => this.close(true));
            this.overlay.addEventListener('click', (e) => {
                if (e.target === this.overlay) this.close(false);
            });
            
            // ESC para fechar
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.overlay.classList.contains('show')) {
                    this.close(false);
                }
            });
            
            // Enter para confirmar
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && this.overlay.classList.contains('show')) {
                    this.close(true);
                }
            });
        },
        
        show(options) {
            return new Promise((resolve) => {
                this.resolveCallback = resolve;
                
                // Normalizar opções
                const opts = typeof options === 'string' 
                    ? { message: options } 
                    : options;
                
                const {
                    title = 'Confirmar',
                    message = 'Deseja continuar?',
                    type = 'confirm',
                    confirmText = 'Confirmar',
                    cancelText = 'Cancelar',
                    showCancel = true,
                    confirmClass = ''
                } = opts;
                
                // Configurar tipo
                const config = this.typeConfig[type] || this.typeConfig.confirm;
                this.iconEl.className = `custom-modal-icon ${config.color}`;
                this.iconI.className = `bi ${config.icon}`;
                
                // Configurar textos
                this.titleEl.textContent = title;
                this.messageEl.textContent = message;
                this.confirmBtn.textContent = confirmText;
                this.cancelBtn.textContent = cancelText;
                
                // Configurar estilo do botão confirm
                this.confirmBtn.className = `custom-modal-btn custom-modal-btn-confirm ${confirmClass || type}`;
                
                // Mostrar/ocultar botão cancelar
                this.cancelBtn.style.display = showCancel ? 'block' : 'none';
                
                // Mostrar modal
                this.overlay.classList.add('show');
                this.confirmBtn.focus();
            });
        },
        
        close(result) {
            this.overlay.classList.remove('show');
            if (this.resolveCallback) {
                this.resolveCallback(result);
                this.resolveCallback = null;
            }
        }
    };
    
    // Inicializar quando DOM estiver pronto
    document.addEventListener('DOMContentLoaded', () => CustomModal.init());
    
    /**
     * Mostra modal de confirmação customizado
     * @param {string|object} options - Mensagem ou objeto de opções
     * @returns {Promise<boolean>} - true se confirmou, false se cancelou
     */
    async function customConfirm(options) {
        return CustomModal.show(options);
    }
    
    /**
     * Mostra modal de alerta customizado (sem botão cancelar)
     * @param {string|object} options - Mensagem ou objeto de opções
     * @param {string} type - Tipo do alerta (success, danger, warning, info)
     * @returns {Promise<boolean>} - sempre retorna true ao fechar
     */
    async function customAlert(options, type = 'info') {
        const opts = typeof options === 'string' 
            ? { message: options, type, showCancel: false, confirmText: 'OK', title: getTitleByType(type) } 
            : { ...options, showCancel: false, confirmText: options.confirmText || 'OK' };
        
        return CustomModal.show(opts);
    }
    
    function getTitleByType(type) {
        const titles = {
            success: 'Sucesso',
            danger: 'Erro',
            warning: 'Atenção',
            info: 'Informação',
            confirm: 'Confirmar'
        };
        return titles[type] || 'Aviso';
    }
