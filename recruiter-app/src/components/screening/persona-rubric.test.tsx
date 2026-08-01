// FE coverage for the interviewer-persona rubric editor.
//
// Same pattern as screening-config-panel.test.tsx: spy on the live
// `@/services/screening` exports (restored in afterEach) rather than
// mock.module (process-wide + unrestorable in bun). Wrapped in ToastProvider
// because the component surfaces errors via the shared toast.

import { afterEach, beforeEach, describe, expect, spyOn, test } from 'bun:test';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { ToastProvider } from '@/components/ui/toast';
import type { Persona, PersonaDimension } from '@/services/screening';
import * as screeningModule from '@/services/screening';
import { PersonaRubric } from './persona-rubric';
import { PROBING_PRESETS, WARMTH_PRESETS } from './persona-tone-knobs';

function defined<T>(x: T | null | undefined): T {
  if (x === null || x === undefined) throw new Error('expected defined');
  return x;
}

function mkDimension(overrides: Partial<PersonaDimension> = {}): PersonaDimension {
  return {
    key: 'tone_rapport',
    value: 'Warm, conversational opener',
    confidence: 0.82,
    source: 'cortex',
    ...overrides,
  };
}

function mkPersona(overrides: Partial<Persona> = {}): Persona {
  return {
    personaId: 'persona-1',
    composedText: 'Warm but probing.',
    dimensions: [
      mkDimension({ key: 'tone_rapport', value: 'Warm, conversational opener', source: 'cortex' }),
      mkDimension({
        key: 'probing_depth',
        value: 'Two follow-ups per topic',
        confidence: 0.61,
        source: 'cortex',
      }),
      mkDimension({
        key: 'eval_priorities',
        value: 'Ownership signals',
        confidence: 0.4,
        source: 'generic',
      }),
      mkDimension({
        key: 'must_haves',
        value: 'Ships independently',
        confidence: 0.55,
        source: 'cortex',
      }),
      mkDimension({
        key: 'structure',
        value: '5 min intro, 20 min deep dive',
        confidence: 0.3,
        source: 'generic',
      }),
    ],
    ...overrides,
  };
}

function renderRubric() {
  return render(
    <ToastProvider>
      <PersonaRubric id="pr" requisitionId="req-1" roundId="round-1" />
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
  // The rubric mounts PersonaPicker, which loads the saved-persona library on
  // mount. Stub it so these tests don't hit the network (the picker has its own
  // suite). Each test pushes its own getPersona/derive/save spies on top.
  spies.push(spyOn(screeningModule, 'listPersonas').mockResolvedValue([]));
});

describe('PersonaRubric', () => {
  test('renders the 5 dimension cards with labels, values, source badges, confidence', async () => {
    spies.push(spyOn(screeningModule, 'getPersona').mockResolvedValue(mkPersona()));

    const { container } = renderRubric();

    await waitFor(() => {
      expect(container.querySelector('#pr-dim-tone_rapport')).not.toBeNull();
    });

    // All 5 dimension keys rendered.
    for (const key of [
      'tone_rapport',
      'probing_depth',
      'eval_priorities',
      'must_haves',
      'structure',
    ]) {
      expect(container.querySelector(`#pr-dim-${key}`)).not.toBeNull();
    }

    // Human label + value for one dimension.
    expect(defined(container.querySelector('#pr-dim-tone_rapport-label')).textContent).toContain(
      'Tone & rapport',
    );
    const valueInput = defined(
      container.querySelector('#pr-dim-tone_rapport-value'),
    ) as HTMLTextAreaElement;
    expect(valueInput.value).toBe('Warm, conversational opener');

    // Source badge: cortex → "Cortex", generic → "Generic".
    expect(defined(container.querySelector('#pr-dim-tone_rapport-source')).textContent).toContain(
      'Cortex',
    );
    expect(defined(container.querySelector('#pr-dim-structure-source')).textContent).toContain(
      'Generic',
    );

    // Confidence indicator shows a percentage.
    expect(
      defined(container.querySelector('#pr-dim-tone_rapport-confidence')).textContent,
    ).toContain('82%');
  });

  test('empty initial state shows the derive prompt + Derive button', async () => {
    spies.push(
      spyOn(screeningModule, 'getPersona').mockResolvedValue({
        personaId: null,
        composedText: '',
        dimensions: [],
      }),
    );

    const { container } = renderRubric();

    await waitFor(() => {
      expect(container.querySelector('#pr-empty')).not.toBeNull();
    });
    expect(defined(container.querySelector('#pr-empty')).textContent).toContain('No persona yet');
    expect(container.querySelector('#pr-derive')).not.toBeNull();
  });

  test('Derive from Cortex calls derivePersona and renders returned dimensions', async () => {
    spies.push(
      spyOn(screeningModule, 'getPersona').mockResolvedValue({
        personaId: null,
        composedText: '',
        dimensions: [],
      }),
    );
    const deriveSpy = spyOn(screeningModule, 'derivePersona').mockResolvedValue(mkPersona());
    spies.push(deriveSpy);

    const { container } = renderRubric();

    await waitFor(() => {
      expect(container.querySelector('#pr-derive')).not.toBeNull();
    });

    act(() => {
      fireEvent.click(defined(container.querySelector('#pr-derive')));
    });

    await waitFor(() => {
      expect(container.querySelector('#pr-dim-tone_rapport')).not.toBeNull();
    });
    expect(deriveSpy).toHaveBeenCalledTimes(1);
    expect(deriveSpy.mock.calls[0]?.[0]).toBe('req-1');
    expect(deriveSpy.mock.calls[0]?.[1]).toBe('round-1');
  });

  test('editing a value flips its source to recruiter and Save persona sends it', async () => {
    spies.push(spyOn(screeningModule, 'getPersona').mockResolvedValue(mkPersona()));
    const saveSpy = spyOn(screeningModule, 'savePersona').mockImplementation(
      async (_req, _round, body) => ({
        personaId: 'persona-2',
        composedText: 'recomposed',
        dimensions: body.dimensions,
      }),
    );
    spies.push(saveSpy);

    const { container } = renderRubric();

    await waitFor(() => {
      expect(container.querySelector('#pr-dim-tone_rapport-value')).not.toBeNull();
    });

    const valueInput = defined(
      container.querySelector('#pr-dim-tone_rapport-value'),
    ) as HTMLTextAreaElement;
    act(() => {
      fireEvent.change(valueInput, { target: { value: 'Edited opener' } });
    });

    // Source badge flips to "Edited" locally on edit.
    await waitFor(() => {
      expect(defined(container.querySelector('#pr-dim-tone_rapport-source')).textContent).toContain(
        'Edited',
      );
    });

    act(() => {
      fireEvent.click(defined(container.querySelector('#pr-save')));
    });

    await waitFor(() => {
      expect(saveSpy).toHaveBeenCalledTimes(1);
    });
    const sentBody = saveSpy.mock.calls[0]?.[2] as { dimensions: PersonaDimension[] };
    const edited = sentBody.dimensions.find((d) => d.key === 'tone_rapport');
    expect(edited?.value).toBe('Edited opener');
    expect(edited?.source).toBe('recruiter');
    // Untouched dimension keeps its original source.
    const untouched = sentBody.dimensions.find((d) => d.key === 'structure');
    expect(untouched?.source).toBe('generic');
  });

  test('tone knobs set the style dimensions and ride along on Save persona', async () => {
    spies.push(spyOn(screeningModule, 'getPersona').mockResolvedValue(mkPersona()));
    const saveSpy = spyOn(screeningModule, 'savePersona').mockImplementation(
      async (_req, _round, body) => ({
        personaId: 'persona-2',
        composedText: 'recomposed',
        dimensions: body.dimensions,
      }),
    );
    spies.push(saveSpy);

    const { container } = renderRubric();

    await waitFor(() => {
      expect(container.querySelector('#pr-tone-knobs')).not.toBeNull();
    });

    // Warmth=Warm → tone_rapport, Probing=Deep → probing_depth.
    act(() => {
      fireEvent.click(defined(container.querySelector('#pr-tone-knobs-warmth-warm')));
    });
    act(() => {
      fireEvent.click(defined(container.querySelector('#pr-tone-knobs-probing-deep')));
    });

    act(() => {
      fireEvent.click(defined(container.querySelector('#pr-save')));
    });

    await waitFor(() => {
      expect(saveSpy).toHaveBeenCalledTimes(1);
    });
    const sentBody = saveSpy.mock.calls[0]?.[2] as { dimensions: PersonaDimension[] };

    const tone = sentBody.dimensions.find((d) => d.key === 'tone_rapport');
    expect(tone?.value).toBe(WARMTH_PRESETS.warm);
    expect(tone?.source).toBe('recruiter');

    const probing = sentBody.dimensions.find((d) => d.key === 'probing_depth');
    expect(probing?.value).toBe(PROBING_PRESETS.deep);
    expect(probing?.source).toBe('recruiter');

    // Other dimensions untouched.
    const evalDim = sentBody.dimensions.find((d) => d.key === 'eval_priorities');
    expect(evalDim?.source).toBe('generic');
  });
});
