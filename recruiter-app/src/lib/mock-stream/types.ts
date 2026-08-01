import type { ArtifactType } from '@/types';

export type StreamEvent =
  | { type: 'stage_start' }
  | { type: 'prose_token'; token: string }
  | { type: 'sub_reveal'; sub: string }
  | { type: 'ux_reveal'; component: string; props: Record<string, unknown> }
  | { type: 'artifact_start'; artifactId: string; artifactType: ArtifactType; title: string }
  | { type: 'artifact_patch'; artifactId: string; patch: Record<string, unknown> }
  | { type: 'artifact_complete'; artifactId: string }
  | { type: 'stage_end'; nextStage: string };

export type StreamScript = StreamEvent[];
