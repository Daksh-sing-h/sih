import { useCallback, useEffect, useRef, useState } from "react";
import { OutgoingAudio } from "../audio";
import type { PeerProfile } from "../types";

export type RoomStatus = "idle" | "joining" | "waiting" | "connecting" | "connected" | "left" | "error";

export interface RoomState {
  status: RoomStatus;
  error: string | null;
  me: PeerProfile | null;
  peer: PeerProfile | null;
  remoteStream: MediaStream | null;
  prompt: { phrase: string; at: number } | null;
  micError: string | null;
  connectedAt: number | null;
}

const initial: RoomState = {
  status: "idle",
  error: null,
  me: null,
  peer: null,
  remoteStream: null,
  prompt: null,
  micError: null,
  connectedAt: null,
};

// STUN helps across networks; on one Wi-Fi (or offline) host candidates are enough.
const ICE: RTCConfiguration = { iceServers: [{ urls: "stun:stun.l.google.com:19302" }] };

const wsUrl = (path: string) => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;

export function useRoom(roomId: string) {
  const [state, setState] = useState<RoomState>(initial);
  const ws = useRef<WebSocket | null>(null);
  const pc = useRef<RTCPeerConnection | null>(null);
  const out = useRef<OutgoingAudio | null>(null);
  const pendingIce = useRef<RTCIceCandidateInit[]>([]);

  const send = (msg: object) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(msg));
  };

  const newPeerConnection = useCallback(() => {
    pc.current?.close();
    pendingIce.current = [];
    const conn = new RTCPeerConnection(ICE);
    out.current?.stream.getTracks().forEach((t) => conn.addTrack(t, out.current!.stream));
    conn.onicecandidate = (e) => e.candidate && send({ type: "ice", candidate: e.candidate.toJSON() });
    conn.ontrack = (e) => {
      const stream = e.streams[0] ?? new MediaStream([e.track]);
      setState((s) => ({ ...s, remoteStream: stream }));
    };
    conn.onconnectionstatechange = () => {
      const st = conn.connectionState;
      if (st === "connected") setState((s) => ({ ...s, status: "connected", connectedAt: s.connectedAt ?? Date.now() }));
      if (st === "failed") setState((s) => ({ ...s, status: "error", error: "Couldn't connect the audio. Are both devices on the same network?" }));
    };
    pc.current = conn;
    return conn;
  }, []);

  const flushIce = async () => {
    const conn = pc.current;
    if (!conn?.remoteDescription) return;
    for (const c of pendingIce.current.splice(0)) await conn.addIceCandidate(c).catch(() => {});
  };

  const join = useCallback(
    async (name: string, callerId: string) => {
      setState({ ...initial, status: "joining" });
      try {
        out.current = await OutgoingAudio.create();
        setState((s) => ({ ...s, micError: out.current!.micError }));
        newPeerConnection();
        const q = new URLSearchParams({ name, caller_id: callerId });
        const sock = new WebSocket(wsUrl(`/ws/room/${roomId}?${q}`));
        ws.current = sock;
        sock.onmessage = async (e) => {
          const msg = JSON.parse(e.data);
          switch (msg.type) {
            case "welcome": {
              const peer: PeerProfile | undefined = msg.peers[0];
              setState((s) => ({ ...s, me: msg.you, peer: peer ?? null, status: peer ? "connecting" : "waiting" }));
              break; // if someone is already here, they send the offer
            }
            case "peer_joined": {
              setState((s) => ({ ...s, peer: msg.peer, status: "connecting" }));
              const conn = pc.current ?? newPeerConnection();
              const offer = await conn.createOffer();
              await conn.setLocalDescription(offer);
              send({ type: "offer", sdp: conn.localDescription });
              break;
            }
            case "offer": {
              const conn = pc.current ?? newPeerConnection();
              await conn.setRemoteDescription(msg.sdp);
              await flushIce();
              const answer = await conn.createAnswer();
              await conn.setLocalDescription(answer);
              send({ type: "answer", sdp: conn.localDescription });
              break;
            }
            case "answer":
              await pc.current?.setRemoteDescription(msg.sdp);
              await flushIce();
              break;
            case "ice":
              pendingIce.current.push(msg.candidate);
              await flushIce();
              break;
            case "peer_updated":
              setState((s) => ({ ...s, peer: msg.peer }));
              break;
            case "peer_left":
              newPeerConnection(); // ready for them (or someone else) to rejoin
              setState((s) => ({ ...s, peer: null, remoteStream: null, status: "waiting", connectedAt: null, prompt: null }));
              break;
            case "challenge_prompt":
              setState((s) => ({ ...s, prompt: { phrase: msg.phrase, at: Date.now() } }));
              break;
            case "error":
              setState((s) => ({ ...s, status: "error", error: msg.message }));
              break;
          }
        };
        sock.onclose = () => setState((s) => (s.status === "error" || s.status === "left" ? s : { ...s, status: "left" }));
      } catch (err) {
        setState((s) => ({ ...s, status: "error", error: (err as Error).message }));
      }
    },
    [roomId, newPeerConnection],
  );

  const leave = useCallback(async () => {
    send({ type: "leave" });
    ws.current?.close();
    pc.current?.close();
    pc.current = null;
    await out.current?.close();
    out.current = null;
    setState((s) => ({ ...s, status: "left", remoteStream: null, peer: null, prompt: null }));
  }, []);

  const dismissPrompt = useCallback(() => setState((s) => ({ ...s, prompt: null })), []);

  useEffect(
    () => () => {
      ws.current?.close();
      pc.current?.close();
      void out.current?.close();
    },
    [],
  );

  return { state, join, leave, dismissPrompt, out };
}
