import { afterEach, describe, expect, mock, test } from 'bun:test';
import { act, cleanup, render } from '@testing-library/react';
import { useAutoSaveField } from './use-autosave-field';

afterEach(cleanup);

// A tiny harness that exposes the hook's return value to the test via a ref-like
// callback, and lets the test drive `initial` + `persist` per render.
interface HarnessProps<T> {
  initial: T;
  persist: (v: T) => Promise<unknown>;
  onError?: (err: unknown, v: T) => void;
  isEqual?: (a: T, b: T) => boolean;
  expose: (api: ReturnType<typeof useAutoSaveField<T>>) => void;
}

function Harness<T>({ initial, persist, onError, isEqual, expose }: HarnessProps<T>) {
  const api = useAutoSaveField<T>(initial, persist, { onError, isEqual });
  expose(api);
  return null;
}

describe('useAutoSaveField', () => {
  test('commit(explicitValue) persists the EXPLICIT value, not a stale one', async () => {
    const persisted: string[] = [];
    const persist = mock((v: string) => {
      persisted.push(v);
      return Promise.resolve();
    });
    let api!: ReturnType<typeof useAutoSaveField<string>>;
    render(
      <Harness<string>
        initial="screening"
        persist={persist}
        expose={(a) => {
          api = a;
        }}
      />,
    );

    // Simulate a select onChange that changes the value and commits it in the
    // SAME handler — the old setTimeout(save,0) bug would persist the prior
    // render's value here. The explicit arg must win.
    await act(async () => {
      api.commit('technical');
    });

    expect(persisted).toEqual(['technical']);
    expect(api.value).toBe('technical');
    expect(api.status).toBe('saved');
  });

  test('commit() with no explicit value persists the current edited value', async () => {
    const persisted: string[] = [];
    const persist = mock((v: string) => {
      persisted.push(v);
      return Promise.resolve();
    });
    let api!: ReturnType<typeof useAutoSaveField<string>>;
    render(
      <Harness<string>
        initial="hello"
        persist={persist}
        expose={(a) => {
          api = a;
        }}
      />,
    );

    await act(async () => {
      api.setValue('hello world');
    });
    await act(async () => {
      api.commit();
    });

    expect(persisted).toEqual(['hello world']);
    expect(api.dirty).toBe(false);
  });

  test('commit() on an untouched (non-dirty) field is a no-op', async () => {
    const persist = mock(() => Promise.resolve());
    let api!: ReturnType<typeof useAutoSaveField<string>>;
    render(
      <Harness<string>
        initial="hello"
        persist={persist}
        expose={(a) => {
          api = a;
        }}
      />,
    );

    await act(async () => {
      api.commit();
    });

    expect(persist).not.toHaveBeenCalled();
  });

  test('a failing persist sets status=error + error + calls onError, does NOT throw', async () => {
    const boom = new Error('network down');
    const persist = mock(() => Promise.reject(boom));
    const onError = mock(() => {});
    let api!: ReturnType<typeof useAutoSaveField<string>>;
    render(
      <Harness<string>
        initial="x"
        persist={persist}
        onError={onError}
        expose={(a) => {
          api = a;
        }}
      />,
    );

    // Must not throw out of commit (fire-and-forget internally, surfaced state).
    await act(async () => {
      api.commit('y');
      // let the rejected promise settle
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.status).toBe('error');
    expect(api.error).toBe(boom);
    expect(api.dirty).toBe(true); // stays dirty so the user knows it didn't save
    expect(onError).toHaveBeenCalledTimes(1);
  });

  test('retry() re-runs the last attempted persist', async () => {
    let shouldFail = true;
    const persisted: string[] = [];
    const persist = mock((v: string) => {
      persisted.push(v);
      return shouldFail ? Promise.reject(new Error('fail')) : Promise.resolve();
    });
    let api!: ReturnType<typeof useAutoSaveField<string>>;
    render(
      <Harness<string>
        initial="a"
        persist={persist}
        onError={() => {}}
        expose={(a) => {
          api = a;
        }}
      />,
    );

    await act(async () => {
      api.commit('b');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(api.status).toBe('error');

    shouldFail = false;
    await act(async () => {
      api.retry();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(persisted).toEqual(['b', 'b']);
    expect(api.status).toBe('saved');
  });

  test('reconciles to a new `initial` when not dirty', async () => {
    let api!: ReturnType<typeof useAutoSaveField<string>>;
    const persist = mock(() => Promise.resolve());
    const { rerender } = render(
      <Harness<string>
        initial="server-1"
        persist={persist}
        expose={(a) => {
          api = a;
        }}
      />,
    );
    expect(api.value).toBe('server-1');

    await act(async () => {
      rerender(
        <Harness<string>
          initial="server-2"
          persist={persist}
          expose={(a) => {
            api = a;
          }}
        />,
      );
    });

    expect(api.value).toBe('server-2');
  });

  test('does NOT revert a just-saved value when the stale prop has not refetched', async () => {
    // Models the plan-tab case: `initial` is a fresh object each render. After a
    // successful save the local value moves ahead of the (not-yet-refetched)
    // prop. The hook must NOT flip the displayed value back to the stale prop.
    const persist = mock(() => Promise.resolve());
    let api!: ReturnType<typeof useAutoSaveField<{ category: string }>>;
    const sameCategory = (a: { category: string }, b: { category: string }) =>
      a.category === b.category;
    const { rerender } = render(
      <Harness<{ category: string }>
        initial={{ category: 'screening' }}
        persist={persist}
        isEqual={sameCategory}
        expose={(a) => {
          api = a;
        }}
      />,
    );

    // Commit a new category (select-onChange path).
    await act(async () => {
      api.commit({ category: 'technical' });
    });
    expect(api.value.category).toBe('technical');

    // Parent re-renders with the SAME stale prop (refetch hasn't landed). A new
    // object identity, same value. Must not revert.
    await act(async () => {
      rerender(
        <Harness<{ category: string }>
          initial={{ category: 'screening' }}
          persist={persist}
          isEqual={sameCategory}
          expose={(a) => {
            api = a;
          }}
        />,
      );
    });

    expect(api.value.category).toBe('technical');
  });

  test('does NOT clobber an in-progress edit when `initial` changes', async () => {
    let api!: ReturnType<typeof useAutoSaveField<string>>;
    const persist = mock(() => Promise.resolve());
    const { rerender } = render(
      <Harness<string>
        initial="server-1"
        persist={persist}
        expose={(a) => {
          api = a;
        }}
      />,
    );

    // User starts editing (dirty).
    await act(async () => {
      api.setValue('my local edit');
    });
    expect(api.dirty).toBe(true);

    // An external refetch changes `initial` mid-edit. The local edit must win.
    await act(async () => {
      rerender(
        <Harness<string>
          initial="server-2"
          persist={persist}
          expose={(a) => {
            api = a;
          }}
        />,
      );
    });

    expect(api.value).toBe('my local edit');
  });
});
