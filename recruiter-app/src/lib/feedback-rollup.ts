// Helper module for the per-criterion feedback rollup chips that appear in the
// packet drawer. Owns the icon mapping per EvidenceStatus so the drawer doesn't
// carry that table inline. Pure exports — no React state, no side effects.

import { AlertTriangle, CheckCircle2, XCircle, type LucideIcon } from 'lucide-react';
import type { EvidenceStatus } from '@/domain';

export const ROLLUP_ICON: Record<EvidenceStatus, LucideIcon> = {
  supported: CheckCircle2,
  verified: CheckCircle2,
  partial: AlertTriangle,
  contradicted: XCircle,
  none: AlertTriangle,
};
