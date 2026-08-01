import type { CortexStatCard, CortexTrailStep } from '@/fixtures/cortex-insights';

export interface CortexInsightArtifactData {
  title: string;
  elapsedLabel: string;
  steps: CortexTrailStep[];
  activeStepNum: string | null;
  stats: CortexStatCard[];
  complete: boolean;
}
