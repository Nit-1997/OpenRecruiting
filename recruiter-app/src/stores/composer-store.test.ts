import { beforeEach, describe, expect, test } from 'bun:test';
import { useComposerStore } from './composer-store';

beforeEach(() => {
  useComposerStore.getState().reset();
});

describe('composer-store', () => {
  test('initial state is home scope with empty value', () => {
    const s = useComposerStore.getState();
    expect(s.value).toBe('');
    expect(s.scope.kind).toBe('home');
    expect(s.uploading).toBeNull();
  });

  test('setValue updates value', () => {
    useComposerStore.getState().setValue('hello');
    expect(useComposerStore.getState().value).toBe('hello');
  });

  test('setAgenticScope sets kind + tabId', () => {
    useComposerStore.getState().setAgenticScope('intake');
    const s = useComposerStore.getState();
    expect(s.scope.kind).toBe('agentic');
    if (s.scope.kind === 'agentic') expect(s.scope.tabId).toBe('intake');
  });

  test('setQnaScope sets kind + railId', () => {
    useComposerStore.getState().setQnaScope('roles');
    const s = useComposerStore.getState();
    expect(s.scope.kind).toBe('qna');
    if (s.scope.kind === 'qna') expect(s.scope.railId).toBe('roles');
  });

  test('clearValue empties the input', () => {
    useComposerStore.getState().setValue('abc');
    useComposerStore.getState().clearValue();
    expect(useComposerStore.getState().value).toBe('');
  });

  test('setUploading stores file ref', () => {
    const file = new File(['hi'], 'hi.txt');
    useComposerStore.getState().setUploading(file);
    expect(useComposerStore.getState().uploading?.name).toBe('hi.txt');
  });
});
