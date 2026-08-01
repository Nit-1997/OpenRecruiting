'use client';

import { useEffect, useRef, useState } from 'react';

interface PhotonProps {
  name?: string;
  city?: string;
  state?: string;
  country?: string;
}
interface PhotonFeature {
  properties: PhotonProps;
}

interface Props {
  id: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}

const PHOTON_URL = 'https://photon.komoot.io/api/';
const DEBOUNCE_MS = 250;

function formatLabel(p: PhotonProps): string {
  const parts = [p.name, p.city, p.state, p.country].filter((x): x is string => Boolean(x));
  return Array.from(new Set(parts)).join(', ');
}

// Geo-location autocomplete backed by Photon (photon.komoot.io) — free, no API
// key, CORS-enabled. Free text always flows up (so "Remote · US" stays valid);
// the dropdown is purely additive and silently no-ops if the API is unreachable.
export function LocationAutocomplete({ id, value, onChange, placeholder }: Props) {
  const [query, setQuery] = useState(value);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setQuery(value);
  }, [value]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  function runSearch(q: string) {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    fetch(`${PHOTON_URL}?q=${encodeURIComponent(q)}&limit=5&lang=en`, { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('photon'))))
      .then((data: { features?: PhotonFeature[] }) => {
        const labels = Array.from(
          new Set((data.features ?? []).map((f) => formatLabel(f.properties)).filter(Boolean)),
        );
        setSuggestions(labels);
        setOpen(labels.length > 0);
        setActive(-1);
      })
      .catch(() => {
        /* graceful: behave as a plain text input */
      });
  }

  function handleChange(next: string) {
    setQuery(next);
    onChange(next);
    if (timerRef.current) clearTimeout(timerRef.current);
    if (next.trim().length < 2) {
      setSuggestions([]);
      setOpen(false);
      return;
    }
    timerRef.current = setTimeout(() => runSearch(next.trim()), DEBOUNCE_MS);
  }

  function pick(label: string) {
    onChange(label);
    setQuery(label);
    setOpen(false);
    setSuggestions([]);
    setActive(-1);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || suggestions.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, suggestions.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === 'Enter' && active >= 0) {
      e.preventDefault();
      const chosen = suggestions[active];
      if (chosen) pick(chosen);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  }

  return (
    <div id={id} ref={wrapRef} style={{ position: 'relative' }}>
      <input
        id={`${id}-input`}
        value={query}
        onChange={(e) => handleChange(e.target.value)}
        onFocus={() => {
          if (suggestions.length > 0) setOpen(true);
        }}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        autoComplete="off"
        role="combobox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
      />
      {open && (
        <ul
          id={`${id}-list`}
          // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: ARIA combobox popup; focus stays on the input
          role="listbox"
          style={{
            position: 'absolute',
            top: 'calc(100% + 4px)',
            left: 0,
            right: 0,
            zIndex: 50,
            margin: 0,
            padding: 4,
            listStyle: 'none',
            background: 'var(--card)',
            border: '1px solid var(--border)',
            borderRadius: 12,
            boxShadow: 'var(--shadow-md)',
            maxHeight: 220,
            overflowY: 'auto',
          }}
        >
          {suggestions.map((s, i) => (
            <li
              id={`${id}-opt-${i}`}
              key={s}
              // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: ARIA combobox option; selection via input keyboard + mousedown
              role="option"
              tabIndex={-1}
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(s);
              }}
              onMouseEnter={() => setActive(i)}
              style={{
                padding: '8px 10px',
                borderRadius: 8,
                fontSize: 13.5,
                color: 'var(--text-primary)',
                cursor: 'pointer',
                background: i === active ? 'var(--surface)' : 'transparent',
              }}
            >
              {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
