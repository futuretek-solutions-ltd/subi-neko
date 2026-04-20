from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.ws.connection_manager import connection_manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await connection_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; clients send pings as plain text
            await websocket.receive_text()
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)
