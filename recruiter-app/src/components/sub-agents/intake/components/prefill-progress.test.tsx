import { describe, expect, test } from 'bun:test';
import { render } from '@testing-library/react';
import type { ProcessStage } from '@/types/intake';
import { PrefillProgress } from './prefill-progress';

describe('PrefillProgress', () => {
  test('renders all 4 prefill stage rows even when stages array is empty', () => {
    render(<PrefillProgress id="prog" stages={[]} />);
    expect(document.getElementById('prog-row-check_context')).not.toBeNull();
    expect(document.getElementById('prog-row-parse_jd')).not.toBeNull();
    expect(document.getElementById('prog-row-query_cortex')).not.toBeNull();
    expect(document.getElementById('prog-row-synthesize')).not.toBeNull();
  });

  test('marks completed stages with status data-attr', () => {
    const stages: ProcessStage[] = [
      { name: 'check_context', status: 'completed', output: null, error: null, updated_at: null },
      { name: 'parse_jd', status: 'running', output: null, error: null, updated_at: null },
    ];
    render(<PrefillProgress id="prog" stages={stages} />);
    expect(document.getElementById('prog-row-check_context')?.dataset.status).toBe('completed');
    expect(document.getElementById('prog-row-parse_jd')?.dataset.status).toBe('running');
    expect(document.getElementById('prog-row-query_cortex')?.dataset.status).toBe('pending');
  });

  test('surfaces failed stage error message', () => {
    const stages: ProcessStage[] = [
      {
        name: 'parse_jd',
        status: 'failed',
        output: null,
        error: 'pdf too noisy',
        updated_at: null,
      },
    ];
    const { container } = render(<PrefillProgress id="prog" stages={stages} />);
    expect(container.textContent).toContain('pdf too noisy');
  });
});
