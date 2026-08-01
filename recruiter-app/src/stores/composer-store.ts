import { create } from 'zustand';
import type { RailViewId, SubAgentId } from '@/types';

export type ComposerScope =
  | { kind: 'home' }
  | { kind: 'agentic'; tabId: SubAgentId }
  | { kind: 'qna'; railId: RailViewId };

interface ComposerStoreState {
  value: string;
  scope: ComposerScope;
  uploading: File | null;
  setValue: (v: string) => void;
  clearValue: () => void;
  setHomeScope: () => void;
  setAgenticScope: (tabId: SubAgentId) => void;
  setQnaScope: (railId: RailViewId) => void;
  setUploading: (file: File | null) => void;
  reset: () => void;
}

export const useComposerStore = create<ComposerStoreState>((set) => ({
  value: '',
  scope: { kind: 'home' },
  uploading: null,
  setValue: (v) => set({ value: v }),
  clearValue: () => set({ value: '' }),
  setHomeScope: () => set({ scope: { kind: 'home' } }),
  setAgenticScope: (tabId) => set({ scope: { kind: 'agentic', tabId } }),
  setQnaScope: (railId) => set({ scope: { kind: 'qna', railId } }),
  setUploading: (file) => set({ uploading: file }),
  reset: () => set({ value: '', scope: { kind: 'home' }, uploading: null }),
}));
