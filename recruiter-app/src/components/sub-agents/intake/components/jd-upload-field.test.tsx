import { describe, expect, mock, test } from 'bun:test';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

mock.module('@/lib/intake/jd-parser', () => ({
  parseJdFile: async (f: File) =>
    f.name.includes('bad') ? Promise.reject(new Error('bad pdf')) : Promise.resolve('parsed text'),
  isSupportedJdFile: (f: File) => f.name.endsWith('.pdf') || f.name.endsWith('.docx'),
  MAX_JD_BYTES: 5 * 1024 * 1024,
  UnsupportedJdTypeError: class extends Error {},
  JdTooLargeError: class extends Error {},
  JdParseError: class extends Error {},
}));

import { JdUploadField } from './jd-upload-field';

describe('JdUploadField', () => {
  test('renders textarea bound to value', () => {
    render(<JdUploadField id="jd" value="hello" onChange={() => {}} />);
    const ta = screen.getByLabelText(/job description/i) as HTMLTextAreaElement;
    expect(ta.value).toBe('hello');
  });

  test('calls onChange when textarea edited', () => {
    const onChange = mock((_v: string) => {});
    render(<JdUploadField id="jd" value="" onChange={onChange} />);
    const ta = screen.getByLabelText(/job description/i);
    fireEvent.change(ta, { target: { value: 'pasted jd' } });
    expect(onChange.mock.calls.at(-1)?.[0]).toBe('pasted jd');
  });

  test('successful upload pipes parsed text to onChange', async () => {
    const onChange = mock((_v: string) => {});
    render(<JdUploadField id="jd" value="" onChange={onChange} />);
    const input = document.getElementById('jd-file') as HTMLInputElement;
    const f = new File(['x'], 'good.pdf', { type: 'application/pdf' });
    fireEvent.change(input, { target: { files: [f] } });
    await waitFor(() => expect(onChange.mock.calls.map((c) => c[0])).toContain('parsed text'));
  });

  test('failed parse shows inline error and does not clobber existing text', async () => {
    const onChange = mock((_v: string) => {});
    render(<JdUploadField id="jd" value="prior text" onChange={onChange} />);
    const input = document.getElementById('jd-file') as HTMLInputElement;
    const f = new File(['x'], 'bad.pdf', { type: 'application/pdf' });
    fireEvent.change(input, { target: { files: [f] } });
    await waitFor(() => {
      const err = document.getElementById('jd-error');
      expect(err?.textContent ?? '').toMatch(/paste it here|couldn'?t/i);
    });
    expect(onChange.mock.calls.find((c) => c[0] === '')).toBeUndefined();
  });
});
