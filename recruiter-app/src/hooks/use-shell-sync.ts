'use client';

import { usePathname } from 'next/navigation';
import { useEffect } from 'react';
import { useShellStore } from '@/stores';
import type { RailViewId, SubAgentId } from '@/types';
import { RAIL_VIEW_IDS, SUB_AGENT_IDS } from '@/types';

function parsePath(pathname: string): {
  tab: SubAgentId | null;
  rail: RailViewId | null;
  detail: string | null;
} {
  const segments = pathname.split('/').filter(Boolean);

  if (segments.length === 0) return { tab: null, rail: null, detail: null };

  if (segments[0] === 'view') {
    const rail = segments[1] as RailViewId | undefined;
    if (rail && RAIL_VIEW_IDS.includes(rail)) {
      const detail = segments[2] ?? null;
      return { tab: null, rail, detail };
    }
  }

  const first = segments[0] as SubAgentId;
  if (SUB_AGENT_IDS.includes(first)) {
    return { tab: first, rail: null, detail: null };
  }

  return { tab: null, rail: null, detail: null };
}

export function useShellSync(): void {
  const pathname = usePathname();
  const setActiveTab = useShellStore((s) => s.setActiveTab);
  const setActiveRail = useShellStore((s) => s.setActiveRail);
  const setRailDetail = useShellStore((s) => s.setRailDetail);
  const goHome = useShellStore((s) => s.goHome);

  useEffect(() => {
    const { tab, rail, detail } = parsePath(pathname);
    if (tab) {
      setActiveTab(tab);
    } else if (rail) {
      setActiveRail(rail);
      if (detail) setRailDetail({ viewId: rail, detailId: detail });
      else setRailDetail(null);
    } else {
      goHome();
    }
  }, [pathname, setActiveTab, setActiveRail, setRailDetail, goHome]);
}
