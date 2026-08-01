// FE coverage for the saved-persona library picker.
//
// Same pattern as persona-rubric.test.tsx: spy on the live `@/services/screening`
// exports (restored in afterEach) rather than mock.module (process-wide +
// unrestorable in bun). Wrapped in ToastProvider because the component surfaces
// errors via the shared toast.

import { afterEach, beforeEach, describe, expect, spyOn, test } from 'bun:test';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { ToastProvider } from '@/components/ui/toast';
import type { PersonaDimension, PersonaLibraryItem } from '@/services/screening';
import * as screeningModule from '@/services/screening';
import { PersonaPicker } from './persona-picker';

function defined<T>(x: T | null | undefined): T {
  if (x === null || x === undefined) throw new Error('expected defined');
  return x;
}

function mkLibraryItem(overrides: Partial<PersonaLibraryItem> = {}): PersonaLibraryItem {
  return {
    id: 'persona-lib-1',
    name: 'Blunt senior screener',
    composedText: 'Be blunt and fast.',
    isTemplate: true,
    requisitionId: null,
    derivedAt: '2026-06-01T00:00:00Z',
    dimensions: [
      { key: 'tone_rapport', value: 'Be blunt and fast.', confidence: 1, source: 'recruiter' },
    ],
    ...overrides,
  };
}

const currentDimensions: PersonaDimension[] = [
  { key: 'tone_rapport', value: 'Warm and direct.', confidence: 0.8, source: 'cortex' },
  { key: 'eval_priorities', value: 'Ownership matters.', confidence: 0.6, source: 'cortex' },
];

function renderPicker(props: Partial<React.ComponentProps<typeof PersonaPicker>> = {}) {
  return render(
    <ToastProvider>
      <PersonaPicker
        id="pp"
        requisitionId="req-1"
        roundId="round-1"
        currentDimensions={currentDimensions}
        onApplied={() => {}}
        {...props}
      />
    </ToastProvider>,
  );
}

const spies: Array<ReturnType<typeof spyOn>> = [];
afterEach(() => {
  for (const s of spies) s.mockRestore();
  spies.length = 0;
  cleanup();
});
beforeEach(() => {
  spies.length = 0;
});

describe('PersonaPicker', () => {
  test('lists saved personas from listPersonas', async () => {
    const listSpy = spyOn(screeningModule, 'listPersonas').mockResolvedValue([
      mkLibraryItem(),
      mkLibraryItem({ id: 'persona-lib-2', name: 'Friendly opener' }),
    ]);
    spies.push(listSpy);

    const { container } = renderPicker();

    await waitFor(() => {
      expect(container.querySelector('#pp-option-persona-lib-1')).not.toBeNull();
    });
    expect(container.querySelector('#pp-option-persona-lib-2')).not.toBeNull();
    expect(defined(container.querySelector('#pp-option-persona-lib-1')).textContent).toContain(
      'Blunt senior screener',
    );
    expect(listSpy).toHaveBeenCalledTimes(1);
  });

  test('"Use this persona" calls selectPersona with the chosen id', async () => {
    spies.push(spyOn(screeningModule, 'listPersonas').mockResolvedValue([mkLibraryItem()]));
    const selectSpy = spyOn(screeningModule, 'selectPersona').mockResolvedValue({
      personaId: 'persona-lib-1',
      composedText: 'Be blunt and fast.',
      dimensions: mkLibraryItem().dimensions,
    });
    spies.push(selectSpy);

    const { container } = renderPicker();

    await waitFor(() => {
      expect(container.querySelector('#pp-use-persona-lib-1')).not.toBeNull();
    });

    act(() => {
      fireEvent.click(defined(container.querySelector('#pp-use-persona-lib-1')));
    });

    await waitFor(() => {
      expect(selectSpy).toHaveBeenCalledTimes(1);
    });
    expect(selectSpy.mock.calls[0]?.[0]).toBe('req-1');
    expect(selectSpy.mock.calls[0]?.[1]).toBe('round-1');
    expect(selectSpy.mock.calls[0]?.[2]).toBe('persona-lib-1');
  });

  test('"Save current as template" calls createPersona with is_template true', async () => {
    spies.push(spyOn(screeningModule, 'listPersonas').mockResolvedValue([]));
    const createSpy = spyOn(screeningModule, 'createPersona').mockResolvedValue(mkLibraryItem());
    spies.push(createSpy);

    const { container } = renderPicker();

    await waitFor(() => {
      expect(container.querySelector('#pp-save-template')).not.toBeNull();
    });

    act(() => {
      fireEvent.click(defined(container.querySelector('#pp-save-template')));
    });

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledTimes(1);
    });
    const body = createSpy.mock.calls[0]?.[0] as {
      isTemplate?: boolean;
      dimensions: PersonaDimension[];
    };
    expect(body.isTemplate).toBe(true);
    expect(body.dimensions).toEqual(currentDimensions);
  });

  test('empty list shows the empty state', async () => {
    spies.push(spyOn(screeningModule, 'listPersonas').mockResolvedValue([]));

    const { container } = renderPicker();

    await waitFor(() => {
      expect(container.querySelector('#pp-empty')).not.toBeNull();
    });
    expect(defined(container.querySelector('#pp-empty')).textContent).toContain(
      'No saved personas',
    );
  });
});
