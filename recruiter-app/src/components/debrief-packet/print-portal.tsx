'use client';

import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';

/**
 * Mounts its children directly under <body> as a `.print-portal` element via
 * React.createPortal. The shared `globals.css` `@media print` convention hides
 * everything that is NOT `.print-portal` and reveals the portal, so
 * `window.print()` captures the printable content in place (no separate route).
 * Hidden on screen (`display: none`).
 */
export function PrintPortal({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted || typeof document === 'undefined') return null;
  return createPortal(
    <div className="print-portal" style={{ display: 'none' }}>
      {children}
    </div>,
    document.body,
  );
}
