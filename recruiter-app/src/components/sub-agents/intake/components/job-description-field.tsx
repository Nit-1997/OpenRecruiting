'use client';

import { Loader2, Paperclip, Sparkles, X } from 'lucide-react';
import { useState } from 'react';
import { extractJobDescription, IntakeApiError, type JdExtractResult } from '@/lib/intake/api';

const ACCEPT = '.pdf,.docx,.txt,.md';
const URL_RE = /https?:\/\/\S+/i;

interface Props {
  id: string;
  /** Called with the role-context text to use (formatted on parse; '' to clear). */
  onChange: (jd: string) => void;
}

// One box for role context: paste a job-posting URL, the JD text, and/or any extra
// notes — and/or attach a file. A URL in the text is auto-detected and fetched
// server-side; everything is sanitized + parsed with the LLM down to role context.
export function JobDescriptionField({ id, onChange }: Props) {
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [parsing, setParsing] = useState(false);
  const [parsed, setParsed] = useState<JdExtractResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const hasInput = text.trim().length > 0 || file !== null;
  const hasUrl = URL_RE.test(text);

  async function parse() {
    if (!hasInput || parsing) return;
    setParsing(true);
    setError(null);
    try {
      const res = await extractJobDescription({
        ...(text.trim() ? { text } : {}),
        ...(file ? { file } : {}),
      });
      if (res.status === 'ok') {
        setParsed(res);
        onChange(res.formatted_jd);
      } else if (res.status === 'rejected') {
        setError(
          res.flags.reason
            ? `Couldn't use this — it looks like it contains instructions aimed at the AI (${res.flags.reason}).`
            : "Couldn't safely use this content.",
        );
        onChange('');
      } else {
        setError("Couldn't read role context from that. Try pasting the text directly.");
        onChange('');
      }
    } catch (e) {
      setError(e instanceof IntakeApiError ? e.detail : 'Could not process that.');
      onChange('');
    } finally {
      setParsing(false);
    }
  }

  function reset() {
    setParsed(null);
    setError(null);
    onChange('');
  }

  if (parsing) {
    return (
      <div
        id={`${id}-loading`}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: 16,
          border: '1px solid var(--border)',
          borderRadius: 12,
          color: 'var(--text-muted)',
          fontSize: 13.5,
        }}
      >
        <Loader2 size={16} className="animate-spin" />
        {hasUrl ? 'Fetching and reading the job posting…' : 'Reading the job description…'}
      </div>
    );
  }

  if (parsed?.status === 'ok') {
    const s = parsed.structured;
    return (
      <div
        id={`${id}-result`}
        style={{
          border: '1px solid var(--border)',
          borderRadius: 12,
          padding: 14,
          background: 'var(--surface)',
        }}
      >
        {s?.title && (
          <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text-primary)' }}>
            {s.title}
          </div>
        )}
        {s?.location && (
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11.5,
              color: 'var(--text-muted)',
              marginTop: 3,
            }}
          >
            {s.location}
          </div>
        )}
        {s?.summary && (
          <p
            style={{
              fontSize: 13,
              color: 'var(--text-secondary)',
              margin: '8px 0 0',
              lineHeight: 1.5,
            }}
          >
            {s.summary}
          </p>
        )}
        {(
          [
            ['Responsibilities', s?.responsibilities],
            ['Must-haves', s?.must_haves],
            ['Nice-to-haves', s?.nice_to_haves],
          ] as const
        ).map(([label, items]) =>
          items && items.length > 0 ? (
            <div key={label} style={{ marginTop: 10 }}>
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 9.5,
                  letterSpacing: '0.12em',
                  textTransform: 'uppercase',
                  color: 'var(--text-faint)',
                }}
              >
                {label}
              </div>
              <ul
                style={{
                  margin: '6px 0 0',
                  paddingLeft: 16,
                  fontSize: 13,
                  color: 'var(--text-secondary)',
                  lineHeight: 1.5,
                }}
              >
                {items.map((it) => (
                  <li key={it}>{it}</li>
                ))}
              </ul>
            </div>
          ) : null,
        )}
        <button
          id={`${id}-replace`}
          type="button"
          className="mz-mini-add"
          onClick={reset}
          style={{ marginTop: 12 }}
        >
          Replace
        </button>
      </div>
    );
  }

  return (
    <div id={id}>
      <textarea
        id={`${id}-text`}
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Paste a job-posting URL, the JD, or any context about this role…"
      />

      <div
        style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10, flexWrap: 'wrap' }}
      >
        {file ? (
          <span
            id={`${id}-file-chip`}
            className="mz-chip"
            style={{
              maxWidth: 220,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {file.name}
            <button type="button" aria-label="Remove file" onClick={() => setFile(null)}>
              <X size={12} />
            </button>
          </span>
        ) : (
          <label
            id={`${id}-upload-label`}
            htmlFor={`${id}-file`}
            className="mz-chip-add"
            style={{ cursor: 'pointer' }}
          >
            <Paperclip size={13} />
            Attach file
            <input
              id={`${id}-file`}
              type="file"
              accept={ACCEPT}
              style={{ display: 'none' }}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
        )}

        {hasInput && (
          <button
            id={`${id}-parse`}
            type="button"
            className="mz-btn-ghost mz-btn-sm"
            onClick={parse}
          >
            <Sparkles size={14} />
            {hasUrl ? 'Fetch & parse' : 'Add to role context'}
          </button>
        )}
      </div>

      {error && (
        <div
          id={`${id}-error`}
          style={{ marginTop: 8, fontSize: 12.5, color: 'var(--danger-fg)', lineHeight: 1.45 }}
        >
          {error}
        </div>
      )}
    </div>
  );
}
