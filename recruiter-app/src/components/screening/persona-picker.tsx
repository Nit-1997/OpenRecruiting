'use client';

import { BookmarkPlus, Check, Library, Loader2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useToast } from '@/components/ui/toast';
import {
  createPersona,
  listPersonas,
  type Persona,
  type PersonaDimension,
  type PersonaLibraryItem,
  selectPersona,
} from '@/services/screening';
import { ServiceError } from '@/services/service-error';

export interface PersonaPickerProps {
  id: string;
  requisitionId: string;
  roundId: string;
  /** The rubric's current dimensions — saved when "Save current as template" is
   *  clicked. When empty, the save action is disabled (nothing to save). */
  currentDimensions: PersonaDimension[];
  /** Called with the applied persona after "Use this persona" so the parent can
   *  refresh the rubric to reflect the picked persona. */
  onApplied: (persona: Persona) => void;
}

function errMessage(err: unknown): string {
  if (err instanceof ServiceError) return err.message;
  if (err instanceof Error) return err.message;
  return 'Something went wrong';
}

export function PersonaPicker({
  id,
  requisitionId,
  roundId,
  currentDimensions,
  onApplied,
}: PersonaPickerProps) {
  const { showToast } = useToast();

  const [personas, setPersonas] = useState<PersonaLibraryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [usingId, setUsingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    // Templates first — the reusable org personas are what the picker is for.
    listPersonas({ templates: true })
      .then((items) => {
        if (!cancelled) setPersonas(items);
      })
      .catch((err) => {
        if (!cancelled) showToast(`Could not load saved personas: ${errMessage(err)}`, 'error');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [showToast]);

  useEffect(() => refresh(), [refresh]);

  const handleUse = useCallback(
    async (persona: PersonaLibraryItem) => {
      if (usingId) return;
      setUsingId(persona.id);
      try {
        const applied = await selectPersona(requisitionId, roundId, persona.id);
        onApplied(applied);
        showToast(`Applied "${persona.name ?? 'persona'}" to this round.`, 'success');
      } catch (err) {
        showToast(`Could not apply persona: ${errMessage(err)}`, 'error');
      } finally {
        setUsingId(null);
      }
    },
    [usingId, requisitionId, roundId, onApplied, showToast],
  );

  const handleSaveTemplate = useCallback(async () => {
    if (saving || currentDimensions.length === 0) return;
    setSaving(true);
    try {
      const created = await createPersona({
        name: 'Saved persona',
        dimensions: currentDimensions,
        isTemplate: true,
      });
      setPersonas((curr) => [created, ...curr]);
      showToast('Saved current persona as a reusable template.', 'success');
    } catch (err) {
      showToast(`Could not save template: ${errMessage(err)}`, 'error');
    } finally {
      setSaving(false);
    }
  }, [saving, currentDimensions, showToast]);

  return (
    <section id={id} className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="inline-flex items-center gap-1.5 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
          <Library strokeWidth={1.75} className="h-3.5 w-3.5" />
          Saved personas
        </span>
        <button
          id={`${id}-save-template`}
          type="button"
          disabled={saving || currentDimensions.length === 0}
          onClick={handleSaveTemplate}
          className="inline-flex items-center gap-1.5 rounded-full border border-cortex-500/40 bg-cortex-500/5 px-3 py-1 font-medium font-mono text-[10.5px] text-cortex-500 uppercase tracking-[0.14em] transition hover:bg-cortex-500/10 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? (
            <Loader2 strokeWidth={2} className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <BookmarkPlus strokeWidth={1.75} className="h-3.5 w-3.5" />
          )}
          {saving ? 'Saving…' : 'Save current as template'}
        </button>
      </div>

      {loading ? (
        <p id={`${id}-loading`} className="text-[13px] text-text-muted">
          Loading saved personas…
        </p>
      ) : personas.length === 0 ? (
        <div
          id={`${id}-empty`}
          className="rounded-[12px] border border-border border-dashed bg-surface/40 p-4 text-center text-[12.5px] text-text-muted"
        >
          No saved personas yet — save the current one as a template to reuse it across roles.
        </div>
      ) : (
        <ul className="flex flex-col gap-2">
          {personas.map((p) => (
            <li
              key={p.id}
              id={`${id}-option-${p.id}`}
              className="flex items-center justify-between gap-3 rounded-[10px] border border-border bg-white px-3.5 py-2.5"
            >
              <div className="min-w-0">
                <p className="truncate font-medium font-sans text-[13px] text-text-primary">
                  {p.name ?? 'Untitled persona'}
                </p>
                <p className="truncate text-[11.5px] text-text-muted">
                  {p.dimensions.length} dimension{p.dimensions.length === 1 ? '' : 's'}
                </p>
              </div>
              <button
                id={`${id}-use-${p.id}`}
                type="button"
                disabled={usingId !== null}
                onClick={() => handleUse(p)}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-text-primary bg-text-primary px-3 py-1 font-medium font-sans text-[12px] text-bg transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {usingId === p.id ? (
                  <Loader2 strokeWidth={2} className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Check strokeWidth={2} className="h-3.5 w-3.5" />
                )}
                Use this persona
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
