'use client';

import {
  Archive,
  Briefcase,
  ChevronLeft,
  ChevronRight,
  Clock,
  FileText,
  Inbox,
  MapPin,
  MoreHorizontal,
  Plus,
  Search,
  X,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import {
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useRef,
  useState,
} from 'react';
import { AtsSourceBadge } from '@/components/shared/ats-source-badge';
import { RolesTableSkeleton } from '@/components/shell/skeletons';
import { useToast } from '@/components/ui/toast';
import type { RequisitionStatus } from '@/domain';
import { useDebouncedValue } from '@/hooks/use-debounced-value';
import { useFocusTrap } from '@/hooks/use-focus-trap';
import { useRequisitions } from '@/hooks/use-services';
import { useShellSync } from '@/hooks/use-shell-sync';
import { IntakeApiError, startIntakeForRole } from '@/lib/intake/api';
import { cn } from '@/lib/utils';
import { requisitions } from '@/services';
import type { RoleListItem } from '@/services/requisitions';
import { ServiceError } from '@/services/service-error';

type TabKey = 'open' | 'pending' | 'closed';

const TAB_LABELS: Record<TabKey, string> = {
  open: 'Open',
  pending: 'Pending',
  closed: 'Closed',
};

const TAB_EMPTY: Record<TabKey, string> = {
  open: 'No open roles. Create one to get started.',
  pending: 'No pending roles.',
  closed: 'No closed roles.',
};

const PAGE_SIZE = 10;

interface RolesViewProps {
  id: string;
}

// Design (image attached to the role-list ticket):
//   On page mount → fetch active tab + prefetch the other two role tabs.
//   Each tab has its own page index; switching tabs preserves the page.
//   Status_counts come from the same response (org-wide) — used for tab badges.
//   Per-row `pipeline.{round_count, candidate_count}` ships with each item,
//   so no N+1 fetch per row.
export function RolesView({ id }: RolesViewProps) {
  useShellSync();
  const router = useRouter();
  const tablistRef = useRef<HTMLDivElement | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>('open');
  const [pageByTab, setPageByTab] = useState<Record<TabKey, number>>({
    open: 1,
    pending: 1,
    closed: 1,
  });
  const [query, setQuery] = useState('');
  // Server-side search is debounced so a keystroke storm fires one request
  // once the user pauses. The role-list hooks below take `q` so a match on
  // ANY page surfaces (the old in-memory page-slice filter only saw page 1).
  const debouncedQuery = useDebouncedValue(query.trim(), 280);
  const [kebabOpenFor, setKebabOpenFor] = useState<string | null>(null);
  // Reset each tab to page 1 when the (debounced) query changes — otherwise
  // a narrowed result set would land on a now-empty page ("page 5 of 1").
  // Driven by the debounced value so it stays in lockstep with the fetch.
  useEffect(() => {
    setPageByTab({ open: 1, pending: 1, closed: 1 });
  }, [debouncedQuery]);

  // Three parallel role-list fetches: the active tab is foreground, the other
  // two are prefetched so a tab switch is instant. Each tab keeps its own
  // page index — paging only refetches the tab being paginated.
  // Search is applied SERVER-SIDE via `q` (title + location across the whole
  // org, not just the loaded page). status_counts on each response stays
  // org-wide so tab badges don't change while typing.
  const openPage = useRequisitions('planned', {
    page: pageByTab.open,
    page_size: PAGE_SIZE,
    q: debouncedQuery || undefined,
  });
  const pendingPage = useRequisitions('intake_pending', {
    page: pageByTab.pending,
    page_size: PAGE_SIZE,
    q: debouncedQuery || undefined,
  });
  const closedPage = useRequisitions('closed', {
    page: pageByTab.closed,
    page_size: PAGE_SIZE,
    q: debouncedQuery || undefined,
  });
  // Tab badges read from `status_counts` (org-wide, identical across the three
  // role responses). While loading, fall back to 0 instead of the
  // previous-page's count to avoid stale numbers.
  const statusCounts =
    openPage.data?.status_counts ??
    pendingPage.data?.status_counts ??
    closedPage.data?.status_counts ??
    null;
  const counts: Record<TabKey, number> = {
    open: statusCounts?.open ?? 0,
    pending: statusCounts?.pending ?? 0,
    closed: statusCounts?.closed ?? 0,
  };

  const tabs: { key: TabKey; icon: typeof Inbox; count: number }[] = [
    { key: 'open', icon: Inbox, count: counts.open },
    { key: 'pending', icon: Clock, count: counts.pending },
    { key: 'closed', icon: Archive, count: counts.closed },
  ];

  // Roving tabindex (mirrors top-bar.tsx): Arrow Left/Right move focus across
  // the tablist, wrapping at the ends. Only the active tab is in the Tab
  // order; the rest are reachable via the arrow keys once the tablist holds
  // focus.
  const onTabKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    const buttons = Array.from(
      tablistRef.current?.querySelectorAll<HTMLButtonElement>('button[role="tab"]') ?? [],
    );
    if (buttons.length === 0) return;
    const focused = document.activeElement as HTMLButtonElement | null;
    const idx = focused ? buttons.indexOf(focused) : -1;
    const next =
      e.key === 'ArrowLeft'
        ? idx <= 0
          ? buttons.length - 1
          : idx - 1
        : idx === buttons.length - 1
          ? 0
          : idx + 1;
    e.preventDefault();
    buttons[next]?.focus();
  };

  // Stable id for the single tabpanel that follows the tablist; each tab
  // points at it via aria-controls and the panel points back at the active
  // tab via aria-labelledby.
  const panelId = `${id}-panel`;

  const activeItems: RoleListItem[] =
    activeTab === 'open'
      ? (openPage.data?.items ?? [])
      : activeTab === 'pending'
        ? (pendingPage.data?.items ?? [])
        : (closedPage.data?.items ?? []);

  // Raw page data for the active tab (null until first load for THIS tab).
  // Drives the cold-load skeleton gate below; with the SWR cache a warm revisit
  // has data here immediately and skips the skeleton.
  const activeData =
    activeTab === 'open'
      ? openPage.data
      : activeTab === 'pending'
        ? pendingPage.data
        : closedPage.data;

  const activeTotal: number =
    activeTab === 'open'
      ? (openPage.data?.total ?? 0)
      : activeTab === 'pending'
        ? (pendingPage.data?.total ?? 0)
        : (closedPage.data?.total ?? 0);

  const activePage = pageByTab[activeTab];

  // Role search is server-side (`q` on the role-list hooks above), so
  // `activeItems` already holds the matching page from the whole org. No
  // in-memory page-slice filter — a match on any page is now visible.
  const totalPagesActive = Math.max(1, Math.ceil(activeTotal / PAGE_SIZE));

  return (
    <div id={id} className="pt-6 pb-6 sm:pt-10">
      <header id={`${id}-header`} className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div id={`${id}-header-text`}>
          <h1
            id={`${id}-title`}
            className="font-display text-[30px] text-text-primary leading-[1.05] tracking-[-0.015em] sm:text-[38px]"
          >
            Roles
          </h1>
          <p id={`${id}-sub`} className="mt-1 text-[14px] text-text-muted">
            {counts.open} open · {counts.pending} pending · {counts.closed} closed
          </p>
        </div>
        <button
          id={`${id}-new-btn`}
          type="button"
          onClick={() => router.push('/intake')}
          className="inline-flex items-center gap-2 rounded-full border border-text-primary bg-text-primary px-4 py-2 font-medium font-sans text-[13px] text-white transition-colors hover:bg-[#222]"
        >
          <Plus strokeWidth={1.75} className="h-4 w-4" />
          New role
        </button>
      </header>

      <div
        id={`${id}-tabs`}
        ref={tablistRef}
        role="tablist"
        aria-label="Role status"
        onKeyDown={onTabKeyDown}
        className="mb-4 flex gap-1 overflow-x-auto rounded-[12px] bg-surface p-1"
      >
        {tabs.map((t) => {
          const Icon = t.icon;
          const active = activeTab === t.key;
          return (
            <button
              key={t.key}
              id={`${id}-tab-${t.key}`}
              type="button"
              role="tab"
              aria-selected={active}
              aria-controls={panelId}
              tabIndex={active ? 0 : -1}
              onClick={() => {
                setActiveTab(t.key);
                setQuery('');
              }}
              className={cn(
                'flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-[10px] px-3 py-1.5 font-medium font-sans text-[12.5px] transition-colors sm:flex-1',
                active
                  ? 'bg-white text-text-primary shadow-[0_1px_3px_rgba(0,0,0,0.04)]'
                  : 'text-text-muted hover:text-text-primary',
              )}
            >
              <Icon strokeWidth={1.75} className="h-3.5 w-3.5" />
              <span>{TAB_LABELS[t.key]}</span>
              <span
                id={`${id}-tab-${t.key}-count`}
                className={cn(
                  'font-mono text-[10px] tabular-nums',
                  active ? 'text-text-muted' : 'text-text-faint',
                )}
              >
                {t.count}
              </span>
            </button>
          );
        })}
      </div>

      <div
        id={`${id}-search`}
        className="relative mb-4 flex items-center rounded-[12px] border border-border bg-white px-3 py-2.5 transition-colors focus-within:border-text-primary"
      >
        <Search strokeWidth={1.75} className="mr-2 h-3.5 w-3.5 text-text-muted" aria-hidden />
        <input
          id={`${id}-search-input`}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search roles by title, team, location, or skill…"
          className="min-w-0 flex-1 border-0 bg-transparent text-[13px] text-text-primary placeholder:text-text-muted focus:outline-none"
          aria-label="Search"
        />
        {query && (
          <button
            id={`${id}-search-clear`}
            type="button"
            aria-label="Clear search"
            onClick={() => setQuery('')}
            className="flex h-5 w-5 items-center justify-center rounded-full text-text-muted hover:text-text-primary"
          >
            <X strokeWidth={1.75} className="h-3 w-3" />
          </button>
        )}
      </div>

      <div id={panelId} role="tabpanel" aria-labelledby={`${id}-tab-${activeTab}`}>
        {activeData == null ? (
          <RolesTableSkeleton id={`${id}-skeleton`} rows={PAGE_SIZE} />
        ) : activeItems.length === 0 ? (
          <EmptyState id={`${id}-empty`} message={TAB_EMPTY[activeTab]} />
        ) : (
          <div
            id={`${id}-table`}
            className="divide-y divide-border rounded-[14px] border border-border bg-white"
          >
            <div
              id={`${id}-table-head`}
              className="hidden grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)_36px] items-center gap-3 bg-surface px-4 py-2.5 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em] md:grid"
            >
              <span>Role</span>
              <span>Department</span>
              <span>Owner</span>
              <span>Pipeline</span>
              <span aria-hidden />
            </div>
            {activeItems.map((r) => (
              <RoleRow
                key={r.id}
                id={`${id}-row-${r.id}`}
                role={r}
                onClick={() => router.push(`/view/roles/${r.id}`)}
                kebabOpen={kebabOpenFor === r.id}
                onKebabToggle={() => setKebabOpenFor((prev) => (prev === r.id ? null : r.id))}
              />
            ))}
          </div>
        )}
      </div>

      <Pager
        id={`${id}-pager`}
        page={activePage}
        pageSize={PAGE_SIZE}
        total={activeTotal}
        totalPages={totalPagesActive}
        onPrev={() =>
          setPageByTab((prev) => ({
            ...prev,
            [activeTab]: Math.max(1, prev[activeTab] - 1),
          }))
        }
        onNext={() =>
          setPageByTab((prev) => ({
            ...prev,
            [activeTab]: Math.min(totalPagesActive, prev[activeTab] + 1),
          }))
        }
      />
    </div>
  );
}

interface RoleRowProps {
  id: string;
  role: RoleListItem;
  onClick: () => void;
  kebabOpen: boolean;
  onKebabToggle: () => void;
}

function RoleRow({ id, role, onClick, kebabOpen, onKebabToggle }: RoleRowProps) {
  const router = useRouter();
  const { showToast } = useToast();
  // Server-computed pipeline counts — no fetch per row.
  const candCount = role.pipeline.candidate_count;
  const planRounds = role.pipeline.round_count;
  const canClose = role.status !== 'closed';
  const canReopen = role.status === 'closed';
  // Pending roles (ATS-imported or awaiting publish) have one deterministic
  // path forward: complete the intake. Publishing happens from the intake
  // canvas once the plan is reviewed — never as a bare status flip here.
  const canCompleteIntake = role.status === 'intake_pending';

  // Kebab menu a11y (mirrors profile-popover + add-candidates-menu):
  //  - wrapRef gates the outside-click (covers trigger + menu).
  //  - menuRef + useFocusTrap moves focus into the menu on open, traps
  //    Tab/Shift-Tab inside it, and closes on Escape.
  //  - triggerRef restores focus to the trigger when the menu closes.
  const wrapRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  useFocusTrap(menuRef, kebabOpen, onKebabToggle);

  useEffect(() => {
    if (!kebabOpen) return;
    const onPointerDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) onKebabToggle();
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [kebabOpen, onKebabToggle]);

  // Restore focus to the trigger after the menu closes so keyboard users
  // aren't dumped at the top of the document.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (wasOpen.current && !kebabOpen) triggerRef.current?.focus();
    wasOpen.current = kebabOpen;
  }, [kebabOpen]);

  return (
    <div
      id={id}
      className="group relative flex flex-col gap-2 px-4 py-3.5 transition-colors hover:bg-surface/60 md:grid md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)_36px] md:items-center md:gap-3"
    >
      <button
        id={`${id}-trigger`}
        type="button"
        onClick={onClick}
        className="absolute inset-0 z-10 cursor-pointer"
        aria-label={`Open ${role.role_title}`}
      />
      <div id={`${id}-title-col`} className="pointer-events-none relative z-20 min-w-0">
        <div id={`${id}-title-row`} className="flex items-center gap-2">
          <div
            id={`${id}-title`}
            className="truncate font-medium font-sans text-[14px] text-text-primary"
          >
            {role.role_title}
          </div>
          <StatusChip id={`${id}-status`} status={role.status} />
          <AtsSourceBadge
            id={`${id}-ats-badge`}
            source={role.source}
            provider={role.ats_provider}
          />
        </div>
        <div
          id={`${id}-loc`}
          className="mt-0.5 flex items-center gap-1 truncate text-[12px] text-text-muted"
        >
          <MapPin strokeWidth={1.75} className="h-3 w-3" />
          {role.role_location || '—'}
        </div>
      </div>
      <div
        id={`${id}-dept`}
        className="pointer-events-none relative z-20 flex items-center gap-1.5 text-[12.5px] text-text-muted"
      >
        <Briefcase strokeWidth={1.75} className="h-3 w-3" />
        {role.department}
      </div>
      <div
        id={`${id}-owner`}
        className="pointer-events-none relative z-20 text-[12.5px] text-text-muted"
      >
        {role.created_by_name}
      </div>
      <div
        id={`${id}-pipeline`}
        className="pointer-events-none relative z-20 flex items-center gap-2 text-[12px] text-text-muted"
      >
        <span
          id={`${id}-pipeline-dot`}
          aria-hidden
          className={cn(
            'h-1.5 w-1.5 rounded-full',
            role.status === 'planned'
              ? 'bg-[#10B981]'
              : role.status === 'intake_pending'
                ? 'bg-[#F59E0B]'
                : 'bg-text-muted',
          )}
        />
        <span className="truncate">
          {candCount === 0
            ? `${planRounds} rounds · no candidates yet`
            : `${candCount} candidate${candCount === 1 ? '' : 's'} · ${planRounds} rounds`}
        </span>
      </div>
      <div
        id={`${id}-kebab-wrap`}
        ref={wrapRef}
        className="relative z-30 flex items-center justify-end"
      >
        <button
          id={`${id}-kebab`}
          ref={triggerRef}
          type="button"
          aria-label="Row actions"
          aria-haspopup="menu"
          aria-expanded={kebabOpen}
          onClick={(e) => {
            e.stopPropagation();
            onKebabToggle();
          }}
          className="flex h-7 w-7 items-center justify-center rounded-full text-text-muted opacity-100 transition-opacity hover:border-text-primary hover:text-text-primary md:opacity-0 md:group-hover:opacity-100"
        >
          <MoreHorizontal strokeWidth={1.75} className="h-4 w-4" />
        </button>
        {kebabOpen && (
          <div
            id={`${id}-kebab-menu`}
            ref={menuRef}
            role="menu"
            className="absolute top-8 right-0 z-40 flex min-w-[160px] flex-col overflow-hidden rounded-[10px] border border-border bg-white py-1 shadow-[0_8px_24px_rgba(0,0,0,0.08)]"
          >
            {canCompleteIntake && (
              <KebabItem
                id={`${id}-kebab-complete-intake`}
                label="Complete intake"
                onClick={async () => {
                  try {
                    const { session_id } = await startIntakeForRole(role.id);
                    router.push(`/intake/sessions/${session_id}`);
                  } catch (err) {
                    showToast(
                      err instanceof IntakeApiError ? err.detail : 'Could not start intake',
                      'error',
                    );
                  }
                  onKebabToggle();
                }}
              />
            )}
            {canClose && (
              <KebabItem
                id={`${id}-kebab-close`}
                label="Close"
                onClick={async () => {
                  await requisitions.setStatus(role.id, 'closed').catch(logErr);
                  onKebabToggle();
                }}
              />
            )}
            {canReopen && (
              <KebabItem
                id={`${id}-kebab-reopen`}
                label="Reopen"
                onClick={async () => {
                  await requisitions.setStatus(role.id, 'planned').catch(logErr);
                  onKebabToggle();
                }}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function logErr(err: unknown): void {
  if (err instanceof ServiceError) {
    // biome-ignore lint/suspicious/noConsole: surfaces service errors during demo
    console.warn(`[ops-hub] ${err.code}: ${err.message}`);
  }
}

function StatusChip({ id, status }: { id: string; status: RequisitionStatus }) {
  const cls =
    status === 'planned'
      ? 'bg-[#D1FAE5] text-[#065F46]'
      : status === 'intake_pending'
        ? 'bg-[#FEF3C7] text-[#92400E]'
        : 'bg-surface text-text-muted';
  return (
    <span
      id={id}
      className={cn(
        'inline-flex shrink-0 items-center rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.14em]',
        cls,
      )}
    >
      {status.replace(/_/g, ' ')}
    </span>
  );
}

function KebabItem({ id, label, onClick }: { id: string; label: string; onClick: () => void }) {
  return (
    <button
      id={id}
      type="button"
      role="menuitem"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className="px-3 py-1.5 text-left text-[12.5px] text-text-primary transition-colors hover:bg-surface"
    >
      {label}
    </button>
  );
}

interface PagerProps {
  id: string;
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  onPrev: () => void;
  onNext: () => void;
}

function Pager({ id, page, pageSize, total, totalPages, onPrev, onNext }: PagerProps) {
  if (total <= pageSize) return null;
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(start + pageSize - 1, total);
  return (
    <div
      id={id}
      className="mt-3 flex items-center justify-between rounded-[12px] border border-border bg-white px-3 py-2 text-[12px] text-text-muted"
    >
      <span id={`${id}-range`} className="font-mono tabular-nums">
        {start}–{end} of {total}
      </span>
      <div id={`${id}-controls`} className="flex items-center gap-2">
        <button
          id={`${id}-prev`}
          type="button"
          onClick={onPrev}
          disabled={page <= 1}
          className="flex h-7 w-7 items-center justify-center rounded-full border border-border text-text-muted transition-colors hover:border-text-primary hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border disabled:hover:text-text-muted"
          aria-label="Previous page"
        >
          <ChevronLeft strokeWidth={1.75} className="h-3.5 w-3.5" />
        </button>
        <span id={`${id}-page`} className="font-mono tabular-nums">
          {page} / {totalPages}
        </span>
        <button
          id={`${id}-next`}
          type="button"
          onClick={onNext}
          disabled={page >= totalPages}
          className="flex h-7 w-7 items-center justify-center rounded-full border border-border text-text-muted transition-colors hover:border-text-primary hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border disabled:hover:text-text-muted"
          aria-label="Next page"
        >
          <ChevronRight strokeWidth={1.75} className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

function EmptyState({ id, message }: { id: string; message: string }) {
  return (
    <div
      id={id}
      className="flex flex-col items-center justify-center rounded-[14px] border border-border border-dashed bg-white px-8 py-16 text-center"
    >
      <div
        id={`${id}-icon`}
        className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-surface text-text-muted"
      >
        <FileText strokeWidth={1.75} className="h-5 w-5" />
      </div>
      <p id={`${id}-msg`} className="text-[13px] text-text-muted">
        {message}
      </p>
    </div>
  );
}
