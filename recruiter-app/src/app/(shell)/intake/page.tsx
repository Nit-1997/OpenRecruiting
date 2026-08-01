'use client';

import { IntakeCanvas } from '@/components/sub-agents/intake/canvas';

// Always renders with sessionId=null so the lobby stage shows the history list.
// Using IntakeCanvas directly (not IntakeCanvasAdapter) prevents the store's
// stale sessionId from re-mounting the session overlay after the user clicks back.
export default function IntakePage() {
  return <IntakeCanvas id="intake-canvas" sessionId={null} />;
}
