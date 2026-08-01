'use client';

import type { IntakeSession } from '@/types/intake';
import { SessionActiveStage } from './session-active';

interface Props {
  session: IntakeSession;
}

// Thin wrapper kept for backwards-compat / tests. The canvas renders
// SessionActiveStage directly (one component type for both modalities) so the
// transcript stays mounted across a text↔voice switch.
export function TextActiveStage({ session }: Props) {
  return <SessionActiveStage session={session} mode="text" />;
}
