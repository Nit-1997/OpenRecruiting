import { describe, expect, it, mock } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';
import { ModalitySwitcher } from '../modality-switcher';

const switchTo = mock();

mock.module('@/hooks/intake/use-modality-switch', () => ({
  useModalitySwitch: () => ({
    switchTo,
    isSwitching: null,
    clearSwitchError: mock(),
  }),
}));

describe('ModalitySwitcher', () => {
  it('shows both pills when currentModality is null (ready state)', () => {
    render(<ModalitySwitcher currentModality={null} />);
    expect(document.getElementById('v2-intake-switch-to-chat')).not.toBeNull();
    expect(document.getElementById('v2-intake-switch-to-call')).not.toBeNull();
  });

  it('hides the chat pill when current is text (no self-switch)', () => {
    render(<ModalitySwitcher currentModality="text" />);
    expect(document.getElementById('v2-intake-switch-to-chat')).toBeNull();
    expect(document.getElementById('v2-intake-switch-to-call')).not.toBeNull();
  });

  it('hides the call pill when current is voice (no self-switch)', () => {
    render(<ModalitySwitcher currentModality="voice" />);
    expect(document.getElementById('v2-intake-switch-to-chat')).not.toBeNull();
    expect(document.getElementById('v2-intake-switch-to-call')).toBeNull();
  });

  it('clicking call calls switchTo("voice")', () => {
    switchTo.mockReset();
    render(<ModalitySwitcher currentModality="text" />);
    fireEvent.click(document.getElementById('v2-intake-switch-to-call') as HTMLButtonElement);
    expect(switchTo).toHaveBeenCalledWith('voice');
  });

  it('clicking chat calls switchTo("text")', () => {
    switchTo.mockReset();
    render(<ModalitySwitcher currentModality="voice" />);
    fireEvent.click(document.getElementById('v2-intake-switch-to-chat') as HTMLButtonElement);
    expect(switchTo).toHaveBeenCalledWith('text');
  });
});
