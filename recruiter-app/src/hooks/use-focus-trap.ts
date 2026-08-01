'use client';

import { type RefObject, useEffect } from 'react';

const FOCUSABLE_SELECTOR = [
  'button:not([disabled])',
  '[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/**
 * True when `el` can actually receive focus: not disabled, not visually
 * hidden, not inert, and not inside an aria-hidden subtree. Without these
 * checks, Tab could land on a `display:none`/`inert`/`aria-hidden` node — a
 * focus black hole for keyboard + screen-reader users.
 */
function isFocusable(el: HTMLElement, container: HTMLElement): boolean {
  if (el.hasAttribute('disabled')) return false;

  // `inert` / aria-hidden anywhere up to (and including) the container removes
  // the node from the accessibility + focus order.
  let node: HTMLElement | null = el;
  while (node && node !== container.parentElement) {
    if (node.hasAttribute('inert')) return false;
    if (node.getAttribute('aria-hidden') === 'true') return false;
    node = node.parentElement;
  }

  // Visibility. Prefer computed style (jsdom/happy-dom support it); fall back
  // to inline style + offsetParent so hidden nodes are excluded even when the
  // engine returns an empty computed style.
  const style =
    typeof window !== 'undefined' && window.getComputedStyle ? window.getComputedStyle(el) : null;
  if (style && (style.display === 'none' || style.visibility === 'hidden')) {
    return false;
  }
  if (el.style.display === 'none' || el.style.visibility === 'hidden') {
    return false;
  }
  // offsetParent is null for display:none subtrees (also for position:fixed,
  // which is rare inside a trapped dialog — accept that edge over false hits).
  if (el.offsetParent === null && (!style || style.position !== 'fixed')) {
    // Only treat as hidden when we have a reason to believe it's display:none;
    // happy-dom often returns null offsetParent for everything, so guard on
    // the engine actually reporting layout.
    if (el.getClientRects && el.getClientRects().length === 0) {
      return false;
    }
  }
  return true;
}

function getFocusable(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter((el) =>
    isFocusable(el, container),
  );
}

/**
 * Trap Tab/Shift-Tab focus inside the given container while `active` is true.
 * Also dispatches the supplied `onEscape` callback when Escape is pressed.
 *
 * Used by modal dialogs (roles "+ New role", profile popover) per the P7
 * accessibility pass. Keeps keyboard users inside the dialog — cycling
 * from the last focusable back to the first (and vice-versa) — until they
 * explicitly close it.
 */
export function useFocusTrap(
  ref: RefObject<HTMLElement | null>,
  active: boolean,
  onEscape?: () => void,
): void {
  useEffect(() => {
    if (!active) return;
    const container = ref.current;
    if (!container) return;

    // Focus the first focusable element on open, if focus is still outside.
    const focusables = getFocusable(container);
    if (focusables.length > 0 && !container.contains(document.activeElement)) {
      focusables[0]?.focus();
    }

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onEscape?.();
        return;
      }
      if (e.key !== 'Tab') return;
      const list = getFocusable(container);
      if (list.length === 0) return;
      const first = list[0];
      const last = list[list.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey) {
        if (active === first || !container.contains(active)) {
          e.preventDefault();
          last?.focus();
        }
      } else {
        if (active === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };

    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [ref, active, onEscape]);
}
