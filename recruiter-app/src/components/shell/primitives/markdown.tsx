'use client';

import { Fragment, type ReactNode } from 'react';

/**
 * Minimal chat-bubble markdown renderer for LLM-emitted agent messages.
 *
 * Supports exactly what the debrief/intake agents emit: paragraphs (single
 * newlines become <br/>), **bold**, *italic*, `inline code`, "-"/"*" bullet
 * lists, "1." numbered lists, GFM pipe tables, "#" headings (rendered as a
 * semibold line — never a document heading inside a bubble), and "---" rules
 * (rendered as a thin divider). No dependency, no HTML passthrough, and it
 * re-parses cleanly on every streaming token so partial blocks degrade to
 * plain text instead of breaking the bubble.
 *
 * Plain single-paragraph strings return their inline nodes directly (no block
 * wrapper) so existing scripted greetings render exactly as before.
 */

type Block =
  | { kind: 'paragraph'; lines: string[] }
  | { kind: 'ul'; items: string[] }
  | { kind: 'ol'; items: string[] }
  | { kind: 'heading'; text: string }
  | { kind: 'hr' }
  | { kind: 'table'; header: string[] | null; rows: string[][] };

const BULLET_RE = /^\s*[-*•]\s+(.*)$/;
const ORDERED_RE = /^\s*\d+[.)]\s+(.*)$/;
const HEADING_RE = /^\s*#{1,4}\s+(.*)$/;
const HR_RE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
const TABLE_SEPARATOR_RE = /^\s*\|?[\s:|-]+\|?\s*$/;

function isTableLine(line: string): boolean {
  const trimmed = line.trim();
  return trimmed.startsWith('|') && trimmed.length > 1;
}

function parseTableCells(line: string): string[] {
  let trimmed = line.trim();
  if (trimmed.startsWith('|')) trimmed = trimmed.slice(1);
  if (trimmed.endsWith('|')) trimmed = trimmed.slice(0, -1);
  return trimmed.split('|').map((cell) => cell.trim());
}

function parseBlocks(text: string): Block[] {
  const lines = text.split('\n');
  const blocks: Block[] = [];
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      blocks.push({ kind: 'paragraph', lines: paragraph });
      paragraph = [];
    }
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? '';

    if (line.trim() === '') {
      flushParagraph();
      i++;
      continue;
    }

    if (isTableLine(line)) {
      flushParagraph();
      const tableLines: string[] = [];
      while (i < lines.length && isTableLine(lines[i] ?? '')) {
        tableLines.push(lines[i] ?? '');
        i++;
      }
      const hasSeparator = tableLines.length >= 2 && TABLE_SEPARATOR_RE.test(tableLines[1] ?? '');
      const contentLines = tableLines.filter((l) => !TABLE_SEPARATOR_RE.test(l));
      const cells = contentLines.map(parseTableCells);
      if (hasSeparator && cells.length > 0) {
        blocks.push({ kind: 'table', header: cells[0] ?? [], rows: cells.slice(1) });
      } else {
        blocks.push({ kind: 'table', header: null, rows: cells });
      }
      continue;
    }

    if (HR_RE.test(line)) {
      flushParagraph();
      blocks.push({ kind: 'hr' });
      i++;
      continue;
    }

    const heading = line.match(HEADING_RE);
    if (heading?.[1] !== undefined) {
      flushParagraph();
      blocks.push({ kind: 'heading', text: heading[1] });
      i++;
      continue;
    }

    const bullet = line.match(BULLET_RE);
    if (bullet?.[1] !== undefined) {
      flushParagraph();
      const items: string[] = [];
      while (i < lines.length) {
        const m = (lines[i] ?? '').match(BULLET_RE);
        if (m?.[1] === undefined) break;
        items.push(m[1]);
        i++;
      }
      blocks.push({ kind: 'ul', items });
      continue;
    }

    const ordered = line.match(ORDERED_RE);
    if (ordered?.[1] !== undefined) {
      flushParagraph();
      const items: string[] = [];
      while (i < lines.length) {
        const m = (lines[i] ?? '').match(ORDERED_RE);
        if (m?.[1] === undefined) break;
        items.push(m[1]);
        i++;
      }
      blocks.push({ kind: 'ol', items });
      continue;
    }

    paragraph.push(line);
    i++;
  }
  flushParagraph();
  return blocks;
}

const INLINE_TOKEN_RE = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\s][^*\n]*\*)/g;

/** Parse one LINE of inline markdown (bold / italic / code). Per-line so a
 *  stray asterisk can never italicize across line breaks. */
function renderInline(line: string, keyPrefix: string): ReactNode[] {
  return line.split(INLINE_TOKEN_RE).map((token, i) => {
    const key = `${keyPrefix}-t${i}`;
    if (token.startsWith('`') && token.endsWith('`') && token.length > 2) {
      return (
        <code key={key} className="rounded bg-black/[0.06] px-1 py-px font-mono text-[12px]">
          {token.slice(1, -1)}
        </code>
      );
    }
    if (token.startsWith('**') && token.endsWith('**') && token.length > 4) {
      return (
        <strong key={key} className="font-semibold">
          {token.slice(2, -2)}
        </strong>
      );
    }
    if (token.startsWith('*') && token.endsWith('*') && token.length > 2) {
      return <em key={key}>{token.slice(1, -1)}</em>;
    }
    return <Fragment key={key}>{token}</Fragment>;
  });
}

function renderLines(lines: string[], keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  lines.forEach((line, idx) => {
    // biome-ignore lint/suspicious/noArrayIndexKey: rendering a stable parse of a single prose string; index is fine
    if (idx > 0) out.push(<br key={`${keyPrefix}-br${idx}`} />);
    out.push(...renderInline(line, `${keyPrefix}-l${idx}`));
  });
  return out;
}

function renderBlock(block: Block, key: string): ReactNode {
  switch (block.kind) {
    case 'paragraph':
      return <p key={key}>{renderLines(block.lines, key)}</p>;
    case 'heading':
      return (
        <p key={key} className="font-semibold">
          {renderInline(block.text, key)}
        </p>
      );
    case 'hr':
      return <div key={key} aria-hidden className="my-1 h-px bg-border" />;
    case 'ul':
      return (
        <ul key={key} className="list-disc space-y-1 pl-5">
          {block.items.map((item, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: rendering a stable parse of a single prose string; index is fine
            <li key={`${key}-i${i}`}>{renderInline(item, `${key}-i${i}`)}</li>
          ))}
        </ul>
      );
    case 'ol':
      return (
        <ol key={key} className="list-decimal space-y-1 pl-5">
          {block.items.map((item, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: rendering a stable parse of a single prose string; index is fine
            <li key={`${key}-i${i}`}>{renderInline(item, `${key}-i${i}`)}</li>
          ))}
        </ol>
      );
    case 'table': {
      const colCount = Math.max(block.header?.length ?? 0, ...block.rows.map((r) => r.length), 1);
      const pad = (cells: string[]) =>
        cells.length >= colCount
          ? cells
          : [...cells, ...Array<string>(colCount - cells.length).fill('')];
      return (
        <div key={key} className="overflow-x-auto">
          <table className="w-full border-collapse text-[12.5px]">
            {block.header && (
              <thead>
                <tr>
                  {pad(block.header).map((cell, i) => (
                    <th
                      // biome-ignore lint/suspicious/noArrayIndexKey: rendering a stable parse of a single prose string; index is fine
                      key={`${key}-h${i}`}
                      className="border-border border-b px-2 py-1.5 text-left align-top font-semibold"
                    >
                      {renderInline(cell, `${key}-h${i}`)}
                    </th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {block.rows.map((row, ri) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: rendering a stable parse of a single prose string; index is fine
                <tr key={`${key}-r${ri}`}>
                  {pad(row).map((cell, ci) => (
                    <td
                      // biome-ignore lint/suspicious/noArrayIndexKey: rendering a stable parse of a single prose string; index is fine
                      key={`${key}-r${ri}c${ci}`}
                      className="border-border/60 border-b px-2 py-1.5 text-left align-top"
                    >
                      {renderInline(cell, `${key}-r${ri}c${ci}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
  }
}

/**
 * Render a markdown string into chat-bubble React nodes. Non-string children
 * pass through unchanged (parity with the previous AgentMsg behavior).
 */
export function renderMarkdown(children: ReactNode): ReactNode {
  if (typeof children !== 'string') return children;
  const blocks = parseBlocks(children);
  // A single plain paragraph keeps the legacy inline rendering (no <p> wrapper)
  // so the serif display greeting and short bubbles are pixel-identical.
  if (blocks.length === 1 && blocks[0]?.kind === 'paragraph') {
    return renderLines(blocks[0].lines, 'md');
  }
  return (
    <div className="flex flex-col gap-2">
      {blocks.map((block, i) => renderBlock(block, `md-b${i}`))}
    </div>
  );
}
