import { create } from 'zustand';
import type { ChatTabId } from '@/types';

/**
 * Tracks whether an agent is mid-reply (between a user action and the
 * stage_end event that appends the final agent message). Canvases read this
 * to render a "thinking" indicator in place of the stage UX while the agent
 * is still composing, so pickers/chips never flash in before the chat bubble
 * that explains them.
 */
interface TypingStoreState {
  typing: Partial<Record<ChatTabId, boolean>>;
  start: (agentId: ChatTabId) => void;
  stop: (agentId: ChatTabId) => void;
  reset: () => void;
}

export const useTypingStore = create<TypingStoreState>((set) => ({
  typing: {},
  start: (agentId) => set((s) => ({ typing: { ...s.typing, [agentId]: true } })),
  stop: (agentId) => set((s) => ({ typing: { ...s.typing, [agentId]: false } })),
  reset: () => set({ typing: {} }),
}));
