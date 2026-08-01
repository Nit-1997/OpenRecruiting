import { describe, expect, it, mock } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';
import { ProcessTillNowButton } from '../process-till-now-button';

const runReprocess = mock();
let reprocessingFlag = false;

mock.module('@/hooks/intake/use-process-till-now', () => ({
  useProcessTillNow: () => ({
    runReprocess,
    dismissDiffPanel: mock(),
    isReprocessing: reprocessingFlag,
  }),
}));

describe('ProcessTillNowButton', () => {
  it('renders enabled button with default label', () => {
    reprocessingFlag = false;
    render(<ProcessTillNowButton />);
    const btn = document.getElementById('v2-intake-process-till-now-button') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    expect(btn.textContent ?? '').toMatch(/process till now/i);
  });

  it('clicking invokes runReprocess', () => {
    reprocessingFlag = false;
    runReprocess.mockReset();
    render(<ProcessTillNowButton />);
    fireEvent.click(
      document.getElementById('v2-intake-process-till-now-button') as HTMLButtonElement,
    );
    expect(runReprocess).toHaveBeenCalledTimes(1);
  });

  it('disabled + spinner shown when isReprocessing', () => {
    reprocessingFlag = true;
    render(<ProcessTillNowButton />);
    const btn = document.getElementById('v2-intake-process-till-now-button') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(document.getElementById('v2-intake-process-till-now-spinner')).not.toBeNull();
  });
});
