/**
 * WebRTC plumbing for the Phase 2 voice intake.
 *
 * Browser-native APIs only — RTCPeerConnection, navigator.mediaDevices.getUserMedia,
 * and a hidden <audio autoplay> element for playback. SDP offer/answer relays
 * through the backend POST /intake/sessions/:id/voice/start proxy.
 *
 * Failure modes (spec §6.5):
 *   - 502 from backend → voice agent unreachable.
 *   - 409 from backend → modality conflict.
 *   - pc.connectionState === 'failed' → caller handles one retry then surfaces error.
 *
 * Lifecycle owned by useVoiceCall hook (Task D1). This module exposes pure helpers.
 */

import { startVoiceSession } from './api';

export const REMOTE_AUDIO_ELEMENT_ID = 'v2-intake-voice-remote-audio';

export const ICE_SERVERS: RTCIceServer[] = [
  { urls: 'stun:stun.l.google.com:19302' },
];

export interface WebRTCSession {
  pc: RTCPeerConnection;
  localStream: MediaStream;
  remoteAudio: HTMLAudioElement;
  /** Tear down the PeerConnection + stop mic tracks. Idempotent. */
  close(): void;
}

export interface StartWebRTCOpts {
  sessionId: string;
  /** Called when pc.connectionState transitions — caller maps to store state. */
  onConnectionStateChange?: (state: RTCPeerConnectionState) => void;
}

/**
 * Acquire the persistent hidden <audio> element used for remote playback.
 *
 * We mount it on document.body (not a React-tree node) so a React remount
 * during stage transitions doesn't tear down audio playback mid-call.
 */
export function ensureRemoteAudioElement(id: string = REMOTE_AUDIO_ELEMENT_ID): HTMLAudioElement | null {
  if (typeof document === 'undefined') return null;
  let el = document.getElementById(id) as HTMLAudioElement | null;
  if (!el) {
    el = document.createElement('audio') as HTMLAudioElement;
    el.id = id;
    el.autoplay = true;
    el.style.display = 'none';
    document.body.appendChild(el);
  }
  return el;
}

/**
 * Wait until `pc.iceGatheringState === 'complete'` or `timeoutMs` elapses,
 * whichever comes first. Required because we send the full SDP (with all
 * candidates) in one POST — no trickle ICE on the first cut.
 */
export function waitForIceGatheringComplete(pc: RTCPeerConnection, timeoutMs = 3000): Promise<void> {
  return new Promise((resolve) => {
    if (pc.iceGatheringState === 'complete') { resolve(); return; }
    const onChange = () => {
      if (pc.iceGatheringState === 'complete') {
        pc.removeEventListener('icegatheringstatechange', onChange);
        resolve();
      }
    };
    pc.addEventListener('icegatheringstatechange', onChange);
    setTimeout(() => {
      pc.removeEventListener('icegatheringstatechange', onChange);
      resolve();
    }, timeoutMs);
  });
}

/**
 * Acquire mic + open PeerConnection + complete SDP exchange.
 * Throws on:
 *   - mic permission denied (NotAllowedError, NotFoundError from getUserMedia)
 *   - SDP exchange failure (IntakeApiError from startVoiceSession)
 *   - missing local SDP (setLocalDescription returned nothing)
 *
 * Caller (useVoiceCall) catches and routes to the appropriate voiceError kind.
 */
export async function openWebRTCSession(opts: StartWebRTCOpts): Promise<WebRTCSession> {
  const remoteAudio = ensureRemoteAudioElement();
  if (!remoteAudio) {
    throw new Error('webrtc: no document available — voice requires a browser');
  }

  const localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });

  const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });

  localStream.getTracks().forEach((track) => pc.addTrack(track, localStream));

  pc.ontrack = (event) => {
    const [remote] = event.streams;
    if (remote) remoteAudio.srcObject = remote;
  };

  if (opts.onConnectionStateChange) {
    pc.onconnectionstatechange = () => opts.onConnectionStateChange!(pc.connectionState);
  }

  try {
    const offer = await pc.createOffer({ offerToReceiveAudio: true });
    await pc.setLocalDescription(offer);
    await waitForIceGatheringComplete(pc, 3000);
    const localSdp = pc.localDescription?.sdp;
    if (!localSdp) {
      throw new Error('webrtc: no local SDP after setLocalDescription');
    }
    const answer = await startVoiceSession(opts.sessionId, { sdp: localSdp, type: 'offer' });
    await pc.setRemoteDescription({ type: 'answer', sdp: answer.sdp });
  } catch (err) {
    try { pc.close(); } catch {}
    localStream.getTracks().forEach((t) => t.stop());
    throw err;
  }

  const close = () => {
    try { pc.close(); } catch {}
    localStream.getTracks().forEach((t) => t.stop());
    if (remoteAudio.srcObject) remoteAudio.srcObject = null;
  };

  return { pc, localStream, remoteAudio, close };
}
