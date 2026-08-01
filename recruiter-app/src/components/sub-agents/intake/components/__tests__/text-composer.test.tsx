import { describe, expect, it, mock } from 'bun:test';
import { fireEvent, render, screen } from '@testing-library/react';
import { TextComposer } from '../text-composer';

describe('TextComposer', () => {
  it('disables send button when input is empty', () => {
    render(<TextComposer onSend={mock()} disabled={false} />);
    const btn = screen.getByRole('button', { name: /send/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('enables send button when input has non-whitespace', () => {
    render(<TextComposer onSend={mock()} disabled={false} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'hi' } });
    const btn = screen.getByRole('button', { name: /send/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it('calls onSend with trimmed text and clears input', () => {
    const onSend = mock();
    render(<TextComposer onSend={onSend} disabled={false} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '  hello  ' } });
    fireEvent.click(screen.getByRole('button', { name: /send/i }));
    expect(onSend).toHaveBeenCalledWith('hello');
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('');
  });

  it('Enter (no shift) submits; Shift+Enter inserts newline', () => {
    const onSend = mock();
    render(<TextComposer onSend={onSend} disabled={false} />);
    const ta = screen.getByRole('textbox');
    fireEvent.change(ta, { target: { value: 'hi' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(onSend).toHaveBeenCalledWith('hi');

    fireEvent.change(ta, { target: { value: 'a' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: true });
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it('rejects submit while disabled (send-while-in-flight)', () => {
    const onSend = mock();
    render(<TextComposer onSend={onSend} disabled={true} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'hi' } });
    fireEvent.click(screen.getByRole('button', { name: /send/i }));
    expect(onSend).not.toHaveBeenCalled();
  });

  it('keeps the send button disabled while a reply is in flight', () => {
    render(<TextComposer onSend={mock()} disabled={true} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'hi' } });
    const btn = screen.getByRole('button', { name: /send/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});
