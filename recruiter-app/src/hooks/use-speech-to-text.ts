'use client';

import { createClient, LiveTranscriptionEvents } from '@deepgram/sdk';
import { useCallback, useRef, useState } from 'react';

// Per-field voice dictation for the feedback edit screen. Fetches a 60s
// Deepgram key from our BFF (/api/deepgram), authorized by the interviewer's
// feedback session token, then streams mic audio to Deepgram live STT and
// emits transcripts to the caller (which appends finals into the active field).

interface UseSpeechToTextOptions {
  onTranscript?: (transcript: string, isFinal: boolean) => void;
  feedbackSessionToken?: string | null;
}

interface UseSpeechToTextReturn {
  isListening: boolean;
  isConnecting: boolean;
  error: string | null;
  startListening: () => Promise<void>;
  stopListening: () => void;
}

export function useSpeechToText(options: UseSpeechToTextOptions = {}): UseSpeechToTextReturn {
  const { onTranscript, feedbackSessionToken } = options;
  const [isListening, setIsListening] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connectionRef = useRef<ReturnType<
    ReturnType<typeof createClient>['listen']['live']
  > | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const stopListening = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    if (connectionRef.current) {
      connectionRef.current.requestClose();
      connectionRef.current = null;
    }
    if (streamRef.current) {
      for (const track of streamRef.current.getTracks()) track.stop();
    }
    mediaRecorderRef.current = null;
    streamRef.current = null;
    setIsListening(false);
    setIsConnecting(false);
  }, []);

  const startListening = useCallback(async () => {
    setError(null);
    setIsConnecting(true);
    try {
      const headers: Record<string, string> = {};
      if (feedbackSessionToken) headers['x-feedback-session'] = feedbackSessionToken;

      const response = await fetch('/api/deepgram', { headers });
      const { apiKey, error: apiError } = (await response.json()) as {
        apiKey?: string;
        error?: string;
      };
      if (apiError || !apiKey) throw new Error(apiError || 'Failed to get dictation key');

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      streamRef.current = stream;

      const deepgram = createClient(apiKey);
      const connection = deepgram.listen.live({
        model: 'nova-2',
        punctuate: true,
        interim_results: true,
        language: 'en',
      });
      connectionRef.current = connection;

      connection.on(LiveTranscriptionEvents.Open, () => {
        setIsConnecting(false);
        setIsListening(true);
        const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4';
        const mediaRecorder = new MediaRecorder(stream, { mimeType });
        mediaRecorderRef.current = mediaRecorder;
        mediaRecorder.ondataavailable = (event) => {
          if (event.data.size > 0 && connectionRef.current) {
            connection.send(event.data);
          }
        };
        mediaRecorder.start(250);
      });

      connection.on(LiveTranscriptionEvents.Transcript, (data) => {
        const transcript = data.channel?.alternatives?.[0]?.transcript;
        const isFinal = data.is_final === true;
        if (transcript && onTranscript) onTranscript(transcript, isFinal);
      });

      connection.on(LiveTranscriptionEvents.Error, () => {
        setError('Dictation error — please try again.');
        stopListening();
      });

      connection.on(LiveTranscriptionEvents.Close, () => {
        setIsListening(false);
        setIsConnecting(false);
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start dictation.');
      setIsConnecting(false);
      stopListening();
    }
  }, [onTranscript, feedbackSessionToken, stopListening]);

  return { isListening, isConnecting, error, startListening, stopListening };
}
