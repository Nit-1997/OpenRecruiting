'use client';

import { useEffect } from 'react';

/**
 * P7 keyboard shortcuts per spec Section 8 accessibility baseline:
 * - ⌘K / Ctrl+K focuses the composer input (home, agentic, and qna).
 *   If the qna composer is mounted inside a rail chat, we prefer that.
 *   Otherwise we focus the bottom agentic composer input.
 * - Escape is handled locally by overlay owners (right-rail profile,
 *   roles new-form, etc.). This hook does not swallow Escape.
 *
 * The hook is intentionally side-effect only — no state — and mounted
 * once at the shell root so every route gets it.
 */
export function useKeyboardShortcuts(): void {
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      const isMetaK = (e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K');
      if (!isMetaK) return;

      // Don't steal the chord if the user is already typing it into an
      // interaction the browser needs — namely, inside a native editor.
      const target = e.target as HTMLElement | null;
      if (target?.isContentEditable) return;

      e.preventDefault();
      const qna = document.querySelector<HTMLInputElement>('#app-shell-qna-chat-composer-input');
      if (qna) {
        qna.focus();
        return;
      }
      const composer = document.querySelector<HTMLInputElement>('#app-shell-composer-input');
      if (composer) {
        composer.focus();
      }
    };

    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, []);
}
