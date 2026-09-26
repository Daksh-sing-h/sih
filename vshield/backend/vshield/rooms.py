"""Two-person call rooms: WebRTC signaling relay (offer / answer / ICE) plus a
side channel V-Shield uses to push challenge prompts to the person being checked.

Audio never passes through here. The browsers talk peer-to-peer; each browser
separately streams the audio it *receives* to /ws/call for analysis.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from fastapi import WebSocket, WebSocketDisconnect

ROOM_ID = re.compile(r"^[A-Z0-9]{4,12}$")
MAX_PEERS = 2
RELAY = {"offer", "answer", "ice"}


@dataclass
class Peer:
    id: str
    name: str
    caller_id: str
    send: Callable[[dict], Awaitable[None]]

    def profile(self) -> dict:
        return {"id": self.id, "name": self.name, "caller_id": self.caller_id}


@dataclass
class Room:
    id: str
    peers: dict[str, Peer] = field(default_factory=dict)

    def others(self, peer_id: str) -> list[Peer]:
        return [p for pid, p in self.peers.items() if pid != peer_id]


ROOMS: dict[str, Room] = {}


async def send_to(room_id: str, peer_id: str, msg: dict) -> bool:
    room = ROOMS.get(room_id)
    peer = room.peers.get(peer_id) if room else None
    if peer is None:
        return False
    await peer.send(msg)
    return True


async def handle(ws: WebSocket, room_id: str, name: str, caller_id: str):
    await ws.accept()
    room_id = room_id.upper()
    if not ROOM_ID.match(room_id):
        await ws.send_json({"type": "error", "message": "Invalid room code"})
        await ws.close()
        return
    room = ROOMS.setdefault(room_id, Room(room_id))
    if len(room.peers) >= MAX_PEERS:
        await ws.send_json({"type": "error", "message": "This call already has two people in it"})
        await ws.close()
        return

    lock = asyncio.Lock()

    async def send(msg: dict):
        async with lock:
            await ws.send_json(msg)

    me = Peer(uuid.uuid4().hex[:8], name.strip()[:40] or "Guest", caller_id.strip()[:40], send)
    room.peers[me.id] = me
    await send({"type": "welcome", "you": me.profile(), "peers": [p.profile() for p in room.others(me.id)]})
    for other in room.others(me.id):
        # the person already waiting makes the WebRTC offer
        await other.send({"type": "peer_joined", "peer": me.profile()})
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("type")
            if kind in RELAY:
                for other in room.others(me.id):
                    await other.send({**msg, "from": me.id})
            elif kind == "profile":
                me.name = str(msg.get("name", me.name))[:40]
                me.caller_id = str(msg.get("caller_id", me.caller_id))[:40]
                for other in room.others(me.id):
                    await other.send({"type": "peer_updated", "peer": me.profile()})
            elif kind == "leave":
                break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        room.peers.pop(me.id, None)
        for other in room.others(me.id):
            try:
                await other.send({"type": "peer_left", "peer": me.id})
            except RuntimeError:
                pass
        if not room.peers:
            ROOMS.pop(room_id, None)
