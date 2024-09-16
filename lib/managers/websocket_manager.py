import json
from typing import Dict, List

from fastapi import WebSocket
from singleton_decorator import singleton


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
        print(f"Connected: {connection_id} in group: {group}")
        print(f"Current active connections: {self.active_connections}")

    def disconnect(self, websocket: WebSocket, group: str):
        connection_id = str(id(websocket))
        if (
            group in self.active_connections
            and connection_id in self.active_connections[group]
        ):
            del self.active_connections[group][connection_id]
            if not self.active_connections[group]:
                del self.active_connections[group]
        print(f"Disconnected: {connection_id} from group: {group}")
        print(f"Current active connections: {self.active_connections}")

    async def send_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str, group: str):
        print("==> new boardcast message arrived: ", message)
        print("==> broadcast group: ", group)
        print("==> Active connections: ", self.active_connections)

        if group in self.active_connections:
            for connection in self.active_connections[group].values():
                await self.send_message(message, connection)
