'use client';

import { Check } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { saveDebrief } from '@/lib/debrief/api';

interface SaveDebriefButtonProps {
  id: string;
  /** The backend draft packet id to commit (draft → fresh). */
  packetId: string;
  /** Requisition/role id for the post-save deep-link to the role's Debrief tab. */
  roleId: string;
}

/**
 * Commits a generated debrief draft (draft → fresh) and hands off to the role's
 * Debrief tab. Lives in the packet toolbar next to Download (the toolbar `trailing`
 * slot); only rendered for a real v2 `draft` packet, so a mock/already-committed
 * packet shows no Save action. Surfaces save failures inline (never swallowed).
 */
export function SaveDebriefButton({ id, packetId, roleId }: SaveDebriefButtonProps) {
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const onSave = async () => {
    if (!packetId || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      await saveDebrief(packetId);
      router.push(`/view/roles/${roleId}?debrief=${packetId}`);
    } catch (err) {
      // Surface the failure (no silent swallow); stay on the packet.
      setSaveError(err instanceof Error ? err.message : 'Could not save the debrief packet.');
      setSaving(false);
    }
  };

  return (
    <div id={`${id}-save-wrap`} className="flex items-center gap-2 print:hidden">
      {saveError && (
        <span
          id={`${id}-save-error`}
          title={saveError}
          className="max-w-[160px] truncate text-[#B91C1C] text-[11px]"
        >
          {saveError}
        </span>
      )}
      <button
        id={`${id}-save`}
        type="button"
        onClick={() => void onSave()}
        disabled={saving}
        className="inline-flex items-center gap-1.5 rounded-full border border-text-primary bg-text-primary px-3 py-1.5 font-medium font-sans text-[12px] text-white transition-colors hover:bg-[#222] disabled:cursor-not-allowed disabled:opacity-60"
      >
        <Check strokeWidth={2} className="h-3.5 w-3.5" />
        {saving ? 'Saving…' : 'Save debrief'}
      </button>
    </div>
  );
}
