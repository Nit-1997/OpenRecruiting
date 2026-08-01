import type { SubAgentId } from '@/types';

export interface StageFallback {
  text: string;
  chips: Array<{ label: string; value: string; primary?: boolean }>;
}

type StageFallbackBucket = { default: StageFallback } & Record<string, StageFallback | undefined>;

export const STAGE_FALLBACK: Record<SubAgentId | 'default', StageFallbackBucket> = {
  default: {
    default: {
      text: 'Got it. Let me think through what you want here.',
      chips: [
        { label: 'Show me options', value: 'options', primary: true },
        { label: 'Never mind', value: 'dismiss' },
      ],
    },
  },
  intake: {
    default: {
      text: 'Noted. Want me to open the draft requisition or keep talking?',
      chips: [
        { label: 'Open requisition', value: 'open', primary: true },
        { label: 'Keep talking', value: 'dismiss' },
      ],
    },
  },
  debrief: {
    default: {
      text: 'Pick the candidates you want to compare and I will build the debrief.',
      chips: [{ label: 'Pick candidates', value: 'pick', primary: true }],
    },
  },
  sourcing: {
    default: {
      text: 'Describe the candidate in plain English and I will source matches.',
      chips: [{ label: 'Free-form search', value: 'search', primary: true }],
    },
  },
  brain: {
    default: {
      text: 'Ask me anything about your pipeline — velocity, drift, signals.',
      chips: [{ label: 'Show insights', value: 'insights', primary: true }],
    },
  },
};
