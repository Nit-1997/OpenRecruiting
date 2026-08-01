'use client';

import { useRef, useState } from 'react';
import { isSupportedJdFile, MAX_JD_BYTES, parseJdFile } from '@/lib/intake/jd-parser';

interface Props {
  id: string;
  value: string;
  onChange: (jdText: string) => void;
  disabled?: boolean;
}

export function JdUploadField({ id, value, onChange, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [parsing, setParsing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);

    if (!isSupportedJdFile(file)) {
      const maxMb = MAX_JD_BYTES / 1024 / 1024;
      setError(
        file.size > MAX_JD_BYTES
          ? `File is too large (max ${maxMb}MB). Paste it here instead.`
          : `That file type isn't supported — use PDF or .docx, or paste it here.`,
      );
      if (inputRef.current) inputRef.current.value = '';
      return;
    }

    setParsing(true);
    try {
      const text = await parseJdFile(file);
      onChange(text);
    } catch (err) {
      setError(`Couldn't read this file (${(err as Error).message}). Paste it here instead.`);
    } finally {
      setParsing(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  }

  return (
    <div id={id}>
      <label id={`${id}-label`} htmlFor={`${id}-textarea`} className="block text-sm font-medium">
        Job description (optional)
      </label>
      <div id={`${id}-upload-row`} className="mt-2 flex items-center gap-3">
        <input
          id={`${id}-file`}
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          disabled={disabled || parsing}
          onChange={handleFile}
          className="text-sm"
        />
        {parsing && (
          <span id={`${id}-parsing`} className="text-xs text-[var(--text-muted)]">
            reading file…
          </span>
        )}
      </div>
      {error && (
        <div id={`${id}-error`} role="alert" className="mt-2 text-sm text-red-600">
          {error}
        </div>
      )}
      <textarea
        id={`${id}-textarea`}
        rows={6}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || parsing}
        placeholder="Paste the JD here, or upload a PDF/.docx above."
        className="mt-2 block w-full rounded border border-[var(--border)] bg-[var(--surface)] p-2 text-sm"
      />
    </div>
  );
}
