'use client';

import { useState } from 'react';
import type { AnswerStatus, QuestionId } from '@/types/intake';

interface Props {
  qid: QuestionId;
  topic: string;
  initialText: string;
  initialStatus: AnswerStatus;
  saving: boolean;
  errorMessage?: string | null;
  onSave: (patch: { text?: string; status?: AnswerStatus }) => void;
  onCancel: () => void;
}

const STATUS_OPTIONS: AnswerStatus[] = [
  'untouched',
  'needs_probe',
  'discussed',
  'validated',
  'skipped',
];

export function AnswerCardEditor({
  qid,
  topic,
  initialText,
  initialStatus,
  saving,
  errorMessage,
  onSave,
  onCancel,
}: Props) {
  const [text, setText] = useState(initialText);
  const [status, setStatus] = useState<AnswerStatus>(initialStatus);

  const textChanged = text.trim() !== initialText.trim();
  const statusChanged = status !== initialStatus;
  const canSave = !saving && (textChanged || statusChanged);

  const handleSave = () => {
    const patch: { text?: string; status?: AnswerStatus } = {};
    if (textChanged) patch.text = text.trim();
    if (statusChanged) patch.status = status;
    onSave(patch);
  };

  return (
    <div
      id={`v2-intake-editor-${qid}`}
      data-testid={`v2-intake-editor-${qid}`}
      className="space-y-2 p-3 rounded-md"
      style={{ background: 'var(--app-secondary)', border: '1px solid var(--app-border)' }}
    >
      <label
        id={`v2-intake-editor-label-${qid}`}
        htmlFor={`v2-intake-editor-textarea-${qid}`}
        className="block text-xs uppercase tracking-wider"
        style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}
      >
        Editing — {topic}
      </label>
      <textarea
        id={`v2-intake-editor-textarea-${qid}`}
        data-testid={`v2-intake-editor-textarea-${qid}`}
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={saving}
        className="w-full text-sm p-2 rounded-md min-h-[80px]"
        style={{
          background: 'var(--app-card)',
          border: '1px solid var(--app-border)',
          color: 'var(--text-primary)',
        }}
      />
      <div className="flex items-center gap-2">
        <label
          id={`v2-intake-editor-status-label-${qid}`}
          className="text-xs"
          style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}
        >
          Status
        </label>
        <select
          id={`v2-intake-editor-status-${qid}`}
          data-testid={`v2-intake-editor-status-${qid}`}
          value={status}
          onChange={(e) => setStatus(e.target.value as AnswerStatus)}
          disabled={saving}
          className="text-sm px-2 py-1 rounded"
          style={{ background: 'var(--app-card)', border: '1px solid var(--app-border)' }}
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {errorMessage && (
        <div
          id={`v2-intake-editor-error-${qid}`}
          data-testid={`v2-intake-editor-error-${qid}`}
          className="text-xs p-2 rounded"
          style={{ background: 'var(--status-danger-bg)', color: 'var(--status-danger-fg)' }}
        >
          {errorMessage}
        </div>
      )}

      <div className="flex justify-end gap-2 pt-1">
        <button
          id={`v2-intake-editor-cancel-btn-${qid}`}
          data-testid={`v2-intake-editor-cancel-btn-${qid}`}
          type="button"
          onClick={onCancel}
          disabled={saving}
          className="px-3 py-1 rounded text-sm"
          style={{
            background: 'transparent',
            color: 'var(--text-secondary)',
            border: '1px solid var(--app-border)',
          }}
        >
          Cancel
        </button>
        <button
          id={`v2-intake-editor-save-btn-${qid}`}
          data-testid={`v2-intake-editor-save-btn-${qid}`}
          type="button"
          onClick={handleSave}
          disabled={!canSave}
          className="px-3 py-1 rounded text-sm text-white"
          style={{ background: canSave ? 'var(--cortex-500)' : 'var(--text-faint)' }}
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  );
}
