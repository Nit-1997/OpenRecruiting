'use client';

import { ArrowDown, ArrowUp, Plus } from 'lucide-react';
import { useRequisitionStore } from '@/stores';
import { RoundCard } from './round-card';

export interface RoundListProps {
  id: string;
  reqId: string;
  onSelect: (roundId: string) => void;
  buildingRoundIds?: string[];
}

export function RoundList({ id, reqId, onSelect, buildingRoundIds = [] }: RoundListProps) {
  const req = useRequisitionStore((s) => s.requisitions[reqId]);
  const addRound = useRequisitionStore((s) => s.addRound);
  const reorderRounds = useRequisitionStore((s) => s.reorderRounds);

  if (!req) return null;

  const move = (roundId: string, direction: -1 | 1) => {
    const ids = req.rounds.map((r) => r.id);
    const idx = ids.indexOf(roundId);
    const target = idx + direction;
    if (idx < 0 || target < 0 || target >= ids.length) return;
    const a = ids[idx];
    const b = ids[target];
    if (a === undefined || b === undefined) return;
    const next = [...ids];
    next[idx] = b;
    next[target] = a;
    reorderRounds(reqId, next);
  };

  return (
    <section id={id} className="flex flex-col gap-2">
      {req.rounds.map((round, i) => {
        const rowId = `${id}-row-${round.id}`;
        return (
          <div key={round.id} className="group relative">
            <RoundCard
              id={id}
              round={round}
              onSelect={onSelect}
              isBuilding={buildingRoundIds.includes(round.id)}
            />
            <div className="pointer-events-none absolute top-1/2 right-10 flex -translate-y-1/2 flex-col gap-0.5 opacity-0 transition group-hover:pointer-events-auto group-hover:opacity-100">
              <button
                id={`${rowId}-up`}
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  move(round.id, -1);
                }}
                disabled={i === 0}
                aria-label={`Move ${round.name} up`}
                className="flex h-5 w-5 items-center justify-center rounded border border-border bg-bg text-text-muted transition hover:text-text-primary disabled:opacity-30"
              >
                <ArrowUp strokeWidth={1.75} className="h-3 w-3" />
              </button>
              <button
                id={`${rowId}-down`}
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  move(round.id, 1);
                }}
                disabled={i === req.rounds.length - 1}
                aria-label={`Move ${round.name} down`}
                className="flex h-5 w-5 items-center justify-center rounded border border-border bg-bg text-text-muted transition hover:text-text-primary disabled:opacity-30"
              >
                <ArrowDown strokeWidth={1.75} className="h-3 w-3" />
              </button>
            </div>
          </div>
        );
      })}
      <button
        id={`${id}-add`}
        type="button"
        onClick={() => addRound(reqId, { name: 'New round', category: 'behavioral' })}
        className="flex items-center justify-center gap-1.5 rounded-[12px] border border-border border-dashed px-3 py-2.5 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em] transition hover:border-cortex-500/40 hover:text-text-primary"
      >
        <Plus strokeWidth={1.75} className="h-3.5 w-3.5" />
        Add round
      </button>
    </section>
  );
}
