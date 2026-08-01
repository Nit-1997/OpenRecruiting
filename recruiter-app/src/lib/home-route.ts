import { useSessionStore } from '@/stores';
import type { Message, SubAgentId } from '@/types';

export function routeHomeChip(tabId: SubAgentId, seedText: string | null) {
  const sessions = useSessionStore.getState();
  const initialStage =
    tabId === 'intake'
      ? 'mode_choice'
      : tabId === 'debrief'
        ? 'role_pick'
        : tabId === 'sourcing'
          ? 'mode_pick'
          : 'brain';
  if (!sessions.sessions[tabId]) sessions.startSession(tabId, initialStage);
  if (seedText) {
    // Seed the routed message *before* session start so it renders above the
    // stage greeting (in the history tail) rather than below it.
    const current = useSessionStore.getState().sessions[tabId];
    const startedMs = current ? Date.parse(current.startedAt) : Date.now();
    const msg: Message = {
      id:
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      role: 'user',
      text: seedText,
      mode: 'text',
      ts: new Date(startedMs - 1000).toISOString(),
      source: 'chat',
    };
    useSessionStore.getState().appendMessage(tabId, msg);
  }
}

// Route a chat chip. A value starting with '/' is an explicit route (e.g.
// '/view/roles'); any other value is a SubAgentId tab — seed its session with
// the last home user message, then open it.
export function routeChip(router: { push: (path: string) => void }, value: string) {
  if (value.startsWith('/')) {
    router.push(value);
    return;
  }
  const tab = value as SubAgentId;
  const home = useSessionStore.getState().sessions.home;
  const lastUserMsg = home?.messages.filter((m) => m.role === 'user').at(-1)?.text ?? null;
  routeHomeChip(tab, lastUserMsg);
  router.push(`/${tab}`);
}
