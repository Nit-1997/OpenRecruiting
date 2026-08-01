// FE coverage for the persona tone knobs (warmth + probing depth).
//
// The knobs are a fast way to set two persona dimension VALUES (tone_rapport,
// probing_depth) to bounded preset phrases. They don't own state — they reflect
// the current dimension values and call back with the preset phrase so the
// parent rubric updates its dimensions (flipping source to recruiter).

import { afterEach, describe, expect, test } from 'bun:test';
import { act, cleanup, fireEvent, render } from '@testing-library/react';
import { PersonaToneKnobs, PROBING_PRESETS, WARMTH_PRESETS } from './persona-tone-knobs';

function defined<T>(x: T | null | undefined): T {
  if (x === null || x === undefined) throw new Error('expected defined');
  return x;
}

afterEach(cleanup);

describe('PersonaToneKnobs', () => {
  test('renders both knob groups with three options each', () => {
    const { container } = render(
      <PersonaToneKnobs id="tk" toneValue="" probingValue="" onApply={() => {}} />,
    );

    for (const level of ['formal', 'balanced', 'warm']) {
      expect(container.querySelector(`#tk-warmth-${level}`)).not.toBeNull();
    }
    for (const level of ['light', 'standard', 'deep']) {
      expect(container.querySelector(`#tk-probing-${level}`)).not.toBeNull();
    }
  });

  test('selecting Warmth=Warm applies the warm preset to tone_rapport', () => {
    const calls: Array<{ key: string; value: string }> = [];
    const { container } = render(
      <PersonaToneKnobs
        id="tk"
        toneValue=""
        probingValue=""
        onApply={(key, value) => calls.push({ key, value })}
      />,
    );

    act(() => {
      fireEvent.click(defined(container.querySelector('#tk-warmth-warm')));
    });

    expect(calls).toHaveLength(1);
    expect(calls[0]?.key).toBe('tone_rapport');
    expect(calls[0]?.value).toBe(WARMTH_PRESETS.warm);
  });

  test('selecting Probing=Deep applies the deep preset to probing_depth', () => {
    const calls: Array<{ key: string; value: string }> = [];
    const { container } = render(
      <PersonaToneKnobs
        id="tk"
        toneValue=""
        probingValue=""
        onApply={(key, value) => calls.push({ key, value })}
      />,
    );

    act(() => {
      fireEvent.click(defined(container.querySelector('#tk-probing-deep')));
    });

    expect(calls).toHaveLength(1);
    expect(calls[0]?.key).toBe('probing_depth');
    expect(calls[0]?.value).toBe(PROBING_PRESETS.deep);
  });

  test('reflects current dimension values as the active selection', () => {
    const { container } = render(
      <PersonaToneKnobs
        id="tk"
        toneValue={WARMTH_PRESETS.formal}
        probingValue={PROBING_PRESETS.light}
        onApply={() => {}}
      />,
    );

    expect(defined(container.querySelector('#tk-warmth-formal')).getAttribute('aria-pressed')).toBe(
      'true',
    );
    expect(defined(container.querySelector('#tk-warmth-warm')).getAttribute('aria-pressed')).toBe(
      'false',
    );
    expect(defined(container.querySelector('#tk-probing-light')).getAttribute('aria-pressed')).toBe(
      'true',
    );
  });

  test('defaults to Balanced/Standard when values do not match a preset', () => {
    const { container } = render(
      <PersonaToneKnobs
        id="tk"
        toneValue="some bespoke recruiter-written tone"
        probingValue="freeform probing note"
        onApply={() => {}}
      />,
    );

    expect(
      defined(container.querySelector('#tk-warmth-balanced')).getAttribute('aria-pressed'),
    ).toBe('true');
    expect(
      defined(container.querySelector('#tk-probing-standard')).getAttribute('aria-pressed'),
    ).toBe('true');
  });
});
