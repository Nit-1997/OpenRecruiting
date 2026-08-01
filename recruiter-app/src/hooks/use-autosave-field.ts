'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export type AutoSaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export interface UseAutoSaveFieldOptions<T> {
  /**
   * Called with the field's error when a persist() rejects. The hook never
   * swallows the error: it surfaces it here AND via `status='error'`/`error`.
   * Keeps the hook UI-agnostic — the caller wires this to a toast.
   */
  onError?: (error: unknown, value: T) => void;
  /**
   * Compare the live (committed) value against `initial` to decide whether an
   * external change should overwrite the local value during reconciliation.
   * Defaults to `Object.is`.
   */
  isEqual?: (a: T, b: T) => boolean;
}

export interface UseAutoSaveField<T> {
  /** Current local value (controlled-input source of truth). */
  value: T;
  /** Update the local value and mark the field dirty (e.g. onChange). */
  setValue: (next: T) => void;
  /**
   * Persist the CURRENT (or an explicitly-passed) value. Pass the next value
   * explicitly to avoid stale-closure reads (e.g. a `<select>` onChange that
   * sets state and saves in the same handler). No-op when not dirty and no
   * explicit value is given.
   */
  commit: (explicitValue?: T) => void;
  /** Re-run the last failed (or current) persist. */
  retry: () => void;
  status: AutoSaveStatus;
  /** The error from the most recent failed persist, or null. */
  error: unknown;
  dirty: boolean;
}

/**
 * Manages a single auto-saving field.
 *
 * Why this exists: the previous plan-tab editors did `setState(x)` then
 * `setTimeout(save, 0)`, where `save` closed over STALE state from the render
 * that scheduled it — so a `<select>` could persist the PREVIOUS value. And
 * every blur-save was `.catch(logErr)`, so a failed save silently showed the
 * user a populated field that never persisted.
 *
 * This hook fixes both:
 *  - `commit(explicitValue)` passes the NEW value to `persist()` directly — no
 *    setTimeout, no stale closure.
 *  - persist failures set `status='error'` + `error` and call `onError` — never
 *    swallowed. The field stays dirty so the user knows it didn't save and can
 *    retry.
 *  - reconciles to `initial` when it changes externally AND the field isn't
 *    dirty / mid-edit, so an external round refetch doesn't clobber in-progress
 *    edits (and a non-dirty field picks up the fresh server value).
 */
export function useAutoSaveField<T>(
  initial: T,
  persist: (value: T) => Promise<unknown>,
  options: UseAutoSaveFieldOptions<T> = {},
): UseAutoSaveField<T> {
  const { onError } = options;

  const [value, setValueState] = useState<T>(initial);
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<AutoSaveStatus>('idle');
  const [error, setError] = useState<unknown>(null);

  // Refs so reconciliation and async settle handlers always read live values
  // without forcing the effect/callbacks to re-create on every keystroke.
  const valueRef = useRef(value);
  valueRef.current = value;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const persistRef = useRef(persist);
  persistRef.current = persist;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;
  // `isEqual` is held in a ref (callers pass an inline fn that changes identity
  // every render) so the reconcile effect can depend only on `initial`.
  const isEqualRef = useRef(options.isEqual ?? Object.is);
  isEqualRef.current = options.isEqual ?? Object.is;
  // The value last sent to persist — used by retry().
  const lastAttemptedRef = useRef<T>(initial);
  // The last `initial` we reconciled from. We react to EXTERNAL changes of
  // `initial` (prop A → prop B), NOT to divergence between the local value and a
  // stale prop. Without this, a just-saved value (local) would be reverted to
  // the stale prop on the next render before the parent refetches.
  const prevInitialRef = useRef<T>(initial);

  // Reconcile when `initial` changes externally. Adopt the new external value
  // only when the field is NOT dirty (no in-progress edit to clobber). Callers
  // pass a fresh object each render, so we compare by value via `isEqual` to
  // detect a genuine external change. Depends only on `initial` — other reads
  // go through refs.
  // biome-ignore lint/correctness/useExhaustiveDependencies: refs are stable; rerunning on every render would defeat reconciliation.
  useEffect(() => {
    const externalChanged = !isEqualRef.current(prevInitialRef.current, initial);
    if (!externalChanged) return;
    prevInitialRef.current = initial;
    if (!dirtyRef.current) {
      setValueState(initial);
      valueRef.current = initial;
      setStatus('idle');
      setError(null);
    }
  }, [initial]);

  const setValue = useCallback((next: T) => {
    setValueState(next);
    valueRef.current = next;
    setDirty(true);
    dirtyRef.current = true;
  }, []);

  const runPersist = useCallback((toPersist: T) => {
    lastAttemptedRef.current = toPersist;
    setStatus('saving');
    setError(null);
    persistRef.current(toPersist).then(
      () => {
        setStatus('saved');
        setError(null);
        // Only clear dirty if the value hasn't moved on since this attempt
        // started — otherwise we'd hide a newer unsaved edit.
        if (isEqualRef.current(valueRef.current, toPersist)) {
          setDirty(false);
          dirtyRef.current = false;
        }
      },
      (err) => {
        // NEVER swallow: surface via status + error + onError.
        setStatus('error');
        setError(err);
        // Keep dirty so the user knows the save did not land.
        setDirty(true);
        dirtyRef.current = true;
        onErrorRef.current?.(err, toPersist);
      },
    );
  }, []);

  const commit = useCallback(
    (explicitValue?: T) => {
      const hasExplicit = explicitValue !== undefined;
      const next = hasExplicit ? (explicitValue as T) : valueRef.current;
      if (hasExplicit) {
        // Mirror the explicit value into local state so the input reflects it.
        setValueState(next);
        valueRef.current = next;
        setDirty(true);
        dirtyRef.current = true;
      } else if (!dirtyRef.current) {
        // Nothing to save on a plain blur of an untouched field.
        return;
      }
      runPersist(next);
    },
    [runPersist],
  );

  const retry = useCallback(() => {
    runPersist(lastAttemptedRef.current);
  }, [runPersist]);

  return { value, setValue, commit, retry, status, error, dirty };
}
