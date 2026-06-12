"""
WebSocket Support para notificações em tempo real.
Substitui polling por conexões WebSocket para notificações push.

Eventos emitidos:
- notification: Nova notificação do sistema
- stats_update: Atualização de estatísticas
- automation_status: Status da automação
- match_update: Atualização de match específico

Escalabilidade:
- Suporte a Redis como message broker para múltiplas instâncias
- Padrão pub/sub para fan-out de mensagens
"""

import os
from typing import Dict, Set, Optional
from datetime import datetime
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from loguru import logger
import threading
import json

# Configuração do Redis para escalabilidade (opcional)
REDIS_URL = os.getenv('REDIS_URL', None)


def create_socketio(app: Flask) -> SocketIO:
    """
    Cria e configura instância do SocketIO.
    
    Se REDIS_URL estiver configurado, usa Redis como message queue
    para suportar múltiplas instâncias do servidor.
    """
    kwargs = {
        'cors_allowed_origins': [
            'http://localhost:5000',
            'http://127.0.0.1:5000',
            'http://localhost:3000',
        ],
        'async_mode': 'threading',  # Compatível com Flask padrão
        'ping_timeout': 60,
        'ping_interval': 25,
        'max_http_buffer_size': 1024 * 1024  # 1MB
    }
    
    # Usar Redis para escalabilidade se configurado
    if REDIS_URL:
        kwargs['message_queue'] = REDIS_URL
        logger.debug(f"WebSocket: Usando Redis como message broker")
    
    socketio = SocketIO(app, **kwargs)
    
    # Registrar handlers
    register_handlers(socketio)
    
    return socketio


class ConnectionManager:
    """
    Gerencia conexões WebSocket ativas.
    Thread-safe para uso em ambiente multi-threaded.
    """
    
    def __init__(self):
        self._connections: Dict[str, Dict] = {}
        self._rooms: Dict[str, Set[str]] = {}
        self._lock = threading.Lock()
    
    def connect(self, sid: str, data: Optional[Dict] = None):
        """Registra nova conexão."""
        with self._lock:
            self._connections[sid] = {
                'connected_at': datetime.utcnow().isoformat(),
                'data': data or {},
                'rooms': set()
            }
            logger.debug(f"WebSocket conectado: {sid}")
    
    def disconnect(self, sid: str):
        """Remove conexão."""
        with self._lock:
            if sid in self._connections:
                # Remove de todas as rooms
                for room in self._connections[sid].get('rooms', set()):
                    if room in self._rooms:
                        self._rooms[room].discard(sid)
                del self._connections[sid]
                logger.debug(f"WebSocket desconectado: {sid}")
    
    def join_room(self, sid: str, room: str):
        """Adiciona conexão a uma room."""
        with self._lock:
            if sid in self._connections:
                self._connections[sid]['rooms'].add(room)
                if room not in self._rooms:
                    self._rooms[room] = set()
                self._rooms[room].add(sid)
    
    def leave_room(self, sid: str, room: str):
        """Remove conexão de uma room."""
        with self._lock:
            if sid in self._connections:
                self._connections[sid]['rooms'].discard(room)
            if room in self._rooms:
                self._rooms[room].discard(sid)
    
    def get_stats(self) -> Dict:
        """Retorna estatísticas de conexões."""
        with self._lock:
            return {
                'total_connections': len(self._connections),
                'rooms': {room: len(sids) for room, sids in self._rooms.items()},
                'connections': list(self._connections.keys())
            }


# Instância global do gerenciador de conexões
connection_manager = ConnectionManager()


def register_handlers(socketio: SocketIO):
    """Registra event handlers do WebSocket."""
    
    @socketio.on('connect')
    def handle_connect():
        """Handler de nova conexão."""
        sid = request.sid
        connection_manager.connect(sid)
        
        # Colocar na room geral de notificações
        join_room('notifications')
        connection_manager.join_room(sid, 'notifications')
        
        emit('connected', {
            'status': 'connected',
            'sid': sid,
            'timestamp': datetime.utcnow().isoformat()
        })
        
        logger.debug(f"🔌 WebSocket: Cliente conectado (sid={sid[:8]}...)")
    
    @socketio.on('disconnect')
    def handle_disconnect(sid=None):
        """Handler de desconexão."""
        # Flask-SocketIO pode passar sid como argumento ou estar em request.sid
        actual_sid = sid or request.sid
        connection_manager.disconnect(actual_sid)
        logger.debug(f"🔌 WebSocket: Cliente desconectado (sid={actual_sid[:8]}...)")
    
    @socketio.on('subscribe')
    def handle_subscribe(data):
        """
        Permite cliente se inscrever em rooms específicas.
        
        Rooms disponíveis:
        - notifications: Notificações gerais
        - automation: Status da automação
        - match:{id}: Atualizações de match específico
        - stats: Atualizações de estatísticas
        """
        sid = request.sid
        room = data.get('room', 'notifications')
        
        # Validar room
        allowed_rooms = ['notifications', 'automation', 'stats']
        if room.startswith('match:'):
            allowed_rooms.append(room)
        
        if room in allowed_rooms or room.startswith('match:'):
            join_room(room)
            connection_manager.join_room(sid, room)
            emit('subscribed', {'room': room, 'status': 'ok'})
            logger.debug(f"WebSocket: {sid[:8]} inscrito em {room}")
        else:
            emit('error', {'message': f'Room inválida: {room}'})
    
    @socketio.on('unsubscribe')
    def handle_unsubscribe(data):
        """Remove inscrição de uma room."""
        sid = request.sid
        room = data.get('room')
        
        if room:
            leave_room(room)
            connection_manager.leave_room(sid, room)
            emit('unsubscribed', {'room': room, 'status': 'ok'})
    
    @socketio.on('ping')
    def handle_ping():
        """Responde a ping do cliente para manter conexão viva."""
        emit('pong', {'timestamp': datetime.utcnow().isoformat()})
    
    @socketio.on_error_default
    def default_error_handler(e):
        """Handler de erros."""
        logger.error(f"WebSocket erro: {e}")


class WebSocketNotifier:
    """
    Classe para emitir notificações via WebSocket.
    Pode ser usada de qualquer parte da aplicação.
    """
    
    def __init__(self, socketio: Optional[SocketIO] = None):
        self._socketio = socketio
    
    def set_socketio(self, socketio: SocketIO):
        """Define instância do SocketIO."""
        self._socketio = socketio
    
    def emit_notification(self, notification: Dict, room: str = 'notifications'):
        """
        Emite notificação para room especificada.
        
        Args:
            notification: Dados da notificação
            room: Room destino (default: 'notifications')
        """
        if self._socketio:
            self._socketio.emit('notification', notification, room=room)
            logger.debug(f"📤 WebSocket: Notificação emitida para {room}")
    
    def emit_stats_update(self, stats: Dict):
        """Emite atualização de estatísticas."""
        if self._socketio:
            self._socketio.emit('stats_update', {
                'stats': stats,
                'timestamp': datetime.utcnow().isoformat()
            }, room='stats')
    
    def emit_automation_status(self, status: Dict):
        """Emite status da automação."""
        if self._socketio:
            self._socketio.emit('automation_status', {
                'status': status,
                'timestamp': datetime.utcnow().isoformat()
            }, room='automation')
    
    def emit_match_update(self, match_id: int, data: Dict):
        """Emite atualização de match específico."""
        if self._socketio:
            self._socketio.emit('match_update', {
                'match_id': match_id,
                'data': data,
                'timestamp': datetime.utcnow().isoformat()
            }, room=f'match:{match_id}')
    
    def broadcast(self, event: str, data: Dict):
        """Broadcast para todos os clientes conectados."""
        if self._socketio:
            self._socketio.emit(event, data)


# Instância global do notificador
_ws_notifier: Optional[WebSocketNotifier] = None


def get_ws_notifier() -> WebSocketNotifier:
    """Retorna instância global do notificador WebSocket."""
    global _ws_notifier
    if _ws_notifier is None:
        _ws_notifier = WebSocketNotifier()
    return _ws_notifier


# Alias para compatibilidade
get_websocket_notifier = get_ws_notifier


def init_websocket(app: Flask) -> SocketIO:
    """
    Inicializa WebSocket na aplicação Flask.
    
    Args:
        app: Instância do Flask
        
    Returns:
        Instância configurada do SocketIO
    """
    socketio = create_socketio(app)
    
    # Configurar notificador global
    notifier = get_ws_notifier()
    notifier.set_socketio(socketio)
    
    logger.debug("✅ WebSocket inicializado")
    
    return socketio


def get_connection_stats() -> Dict:
    """Retorna estatísticas de conexões WebSocket."""
    return connection_manager.get_stats()
