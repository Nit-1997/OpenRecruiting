import { describe, expect, mock, test } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';
import { PrefillFailedStage } from './prefill-failed';

describe('PrefillFailedStage', () => {
  test('renders banner with continue button', () => {
    render(<PrefillFailedStage id="pf" onContinue={() => {}} />);
    expect(document.getElementById('pf-continue')).not.toBeNull();
  });

  test('fires onContinue when clicked', () => {
    const cb = mock(() => {});
    render(<PrefillFailedStage id="pf" onContinue={cb} />);
    fireEvent.click(document.getElementById('pf-continue') as HTMLButtonElement);
    expect(cb.mock.calls.length).toBe(1);
  });
});
