import { afterEach, beforeEach, describe, expect, it } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';

import { useIntakeStore } from '@/stores/intake-store';
import { ModalityConflictToast } from '../modality-conflict-toast';

describe('ModalityConflictToast', () => {
  beforeEach(() => {
    useIntakeStore.setState({ switchError: null });
  });
  afterEach(() => {
    useIntakeStore.setState({ switchError: null });
  });

  it('renders nothing when switchError is null', () => {
    const { container } = render(<ModalityConflictToast />);
    expect(container.firstChild).toBeNull();
  });

  it('shows conflict message + held/requested context when type=conflict', () => {
    useIntakeStore.setState({
      switchError: {
        type: 'conflict',
        held: 'voice',
        requested: 'text',
        message: 'another mode is currently active',
      },
    });
    const { container } = render(<ModalityConflictToast />);
    expect(document.getElementById('v2-intake-modality-conflict-toast')).not.toBeNull();
    expect(container.textContent ?? '').toMatch(/another mode/i);
  });

  it('shows drain-failed message when type=drain_failed', () => {
    useIntakeStore.setState({
      switchError: { type: 'drain_failed', message: 'drain failed', innerError: 'timeout' },
    });
    const { container } = render(<ModalityConflictToast />);
    expect(document.getElementById('v2-intake-drain-failed-banner')).not.toBeNull();
    expect(container.textContent ?? '').toMatch(/drain failed/i);
  });

  it('shows generic error for type=generic', () => {
    useIntakeStore.setState({ switchError: { type: 'generic', message: 'something broke' } });
    const { container } = render(<ModalityConflictToast />);
    expect(container.textContent ?? '').toMatch(/something broke/i);
  });

  it('dismiss button clears switchError', () => {
    useIntakeStore.setState({
      switchError: { type: 'conflict', held: 'voice', requested: 'text', message: 'x' },
    });
    render(<ModalityConflictToast />);
    fireEvent.click(
      document.getElementById('v2-intake-modality-conflict-toast-dismiss') as HTMLButtonElement,
    );
    expect(useIntakeStore.getState().switchError).toBeNull();
  });
});
