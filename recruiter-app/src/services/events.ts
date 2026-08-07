export type ServiceEventName =
  | 'requisition:created'
  | 'requisition:updated'
  | 'requisition:status_changed'
  | 'requisition:deleted'
  | 'round:created'
  | 'round:updated'
  | 'round:deleted'
  | 'round:reordered'
  | 'question:created'
  | 'question:updated'
  | 'question:deleted'
  | 'candidate:created'
  | 'candidate:updated'
  | 'candidate:deleted'
  | 'candidate:status_changed'
  | 'candidate_round:updated'
  | 'feedback:submitted'
  | 'feedback:requested'
  | 'team:updated'
  | 'billing:updated'
  | 'integration:updated'
  | 'profile:updated'
  | 'notification_prefs:updated'
  | 'activity:created';

type Listener = (payload?: unknown) => void;

const listeners = new Map<ServiceEventName, Set<Listener>>();

export function on(event: ServiceEventName, fn: Listener): () => void {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event)?.add(fn);
  return () => listeners.get(event)?.delete(fn);
}

export function emit(event: ServiceEventName, payload?: unknown): void {
  listeners.get(event)?.forEach((fn) => {
    fn(payload);
  });
}

export function clearAllListeners(): void {
  listeners.clear();
}
