'use client';

interface ResultStageProps {
  id: string;
}

/**
 * Result stage. The "Done. <winner> edges ahead…" agent bubble is rendered by
 * TranscriptTail; the Save action now lives in the packet toolbar next to Download
 * (see `SaveDebriefButton` in the debrief-packet artifact), so this stage no longer
 * renders its own chat-side button. Kept as a no-op stage so the canvas stage
 * machine wiring is unchanged.
 */
export function ResultStage(_props: ResultStageProps) {
  return null;
}
