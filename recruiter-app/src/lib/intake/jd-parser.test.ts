import { describe, expect, test } from 'bun:test';
import { isSupportedJdFile, MAX_JD_BYTES, parseJdFile, UnsupportedJdTypeError } from './jd-parser';

describe('isSupportedJdFile', () => {
  test('accepts application/pdf', () => {
    const f = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'jd.pdf', {
      type: 'application/pdf',
    });
    expect(isSupportedJdFile(f)).toBe(true);
  });

  test('accepts .docx by mime', () => {
    const f = new File([new Uint8Array([0x50, 0x4b])], 'jd.docx', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    });
    expect(isSupportedJdFile(f)).toBe(true);
  });

  test('rejects plain text by extension+mime', () => {
    const f = new File([new TextEncoder().encode('hello')], 'jd.txt', { type: 'text/plain' });
    expect(isSupportedJdFile(f)).toBe(false);
  });

  test('rejects oversized files', () => {
    const big = new File([new Uint8Array(MAX_JD_BYTES + 1)], 'huge.pdf', {
      type: 'application/pdf',
    });
    expect(isSupportedJdFile(big)).toBe(false);
  });
});

describe('parseJdFile', () => {
  test('throws UnsupportedJdTypeError for plain text', async () => {
    const f = new File([new TextEncoder().encode('hi')], 'x.txt', { type: 'text/plain' });
    let err: unknown;
    try {
      await parseJdFile(f);
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(UnsupportedJdTypeError);
  });
});
