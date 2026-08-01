'use client';

import { Fragment } from 'react';

export interface RoleSummaryProps {
  id: string;
  markdown: string;
}

interface ParsedLine {
  key: string;
  value: string;
}

/**
 * Lightweight parser for the canned `**Key:** value` summary format produced by the
 * mock intake pipeline. Falls back to plain-text line rendering when a line isn't
 * in the expected shape. Does NOT attempt to be a general markdown renderer.
 */
function parseLines(markdown: string): Array<ParsedLine | string> {
  return markdown
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = line.match(/^\*\*([^*]+):\*\*\s*(.*)$/);
      if (match) {
        const [, key, value] = match;
        return { key: (key ?? '').trim(), value: (value ?? '').trim() };
      }
      return line;
    });
}

export function RoleSummary({ id, markdown }: RoleSummaryProps) {
  const items = parseLines(markdown);
  return (
    <div
      id={id}
      className="flex flex-col gap-2.5 rounded-[12px] border border-border bg-surface px-4 py-3.5"
    >
      {items.map((item, i) => {
        const key = typeof item === 'string' ? `line-${i}` : `${item.key}-${i}`;
        if (typeof item === 'string') {
          return (
            <p
              key={key}
              id={`${id}-line-${i}`}
              className="font-sans text-[13.5px] text-text-primary leading-relaxed"
            >
              {item}
            </p>
          );
        }
        return (
          <Fragment key={key}>
            <div id={`${id}-row-${i}`} className="grid grid-cols-[110px_1fr] items-start gap-3">
              <span className="pt-0.5 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
                {item.key}
              </span>
              <span className="font-sans text-[13.5px] text-text-primary leading-relaxed">
                {item.value}
              </span>
            </div>
          </Fragment>
        );
      })}
    </div>
  );
}
