import logging
from typing import Dict

from fastapi import WebSocket
from singleton_decorator import singleton

logger = logging.getLogger(__name__)


@singleton
class WebSocketManager:
    def __init__(self, namespace: str):
        self.namespace = namespace
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(self, websocket: WebSocket, group: str):
        await websocket.accept()
        connection_id = str(id(websocket))
        self.active_connections.setdefault(group, {})[
            connection_id
        ] = websocket
        logger.info("ws_connect group=%s connections=%d", group, len(self.active_connections.get(group, {})))

    def disconnect(self, websocket: WebSocket, group: str):
        connection_id = str(id(websocket))
        if (
            group in self.active_connections
            and connection_id in self.active_connections[group]
        ):
            del self.active_connections[group][connection_id]
            if not self.active_connections[group]:
                del self.active_connections[group]
        logger.info("ws_disconnect group=%s", group)

    async def send_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str, group: str):
        if group in self.active_connections:
            for connection in self.active_connections[group].values():
                await self.send_message(message, connection)
