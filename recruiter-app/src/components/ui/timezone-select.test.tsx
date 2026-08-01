import { describe, expect, test } from 'bun:test';
import { fireEvent, render, screen } from '@testing-library/react';
import { TimezoneSelect } from './timezone-select';

function noop() {
  /* test handler */
}

describe('TimezoneSelect', () => {
  test('renders a <select> with the current value selected', () => {
    render(
      <TimezoneSelect id="tz" value="America/New_York" onChange={noop} />,
    );
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    expect(select.value).toBe('America/New_York');
  });

  test('exposes the provided id so external labels can htmlFor it', () => {
    render(<TimezoneSelect id="my-tz" value="UTC" onChange={noop} />);
    const select = document.getElementById('my-tz') as HTMLSelectElement;
    expect(select).not.toBeNull();
    expect(select.tagName).toBe('SELECT');
  });

  test('calls onChange with the new IANA name when the user picks an option', () => {
    let captured = '';
    render(
      <TimezoneSelect
        id="tz"
        value="UTC"
        onChange={(next) => {
          captured = next;
        }}
      />,
    );
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    // happy-dom rejects `value` settings that don't match an existing
    // <option>. Pick a stable, runtime-guaranteed IANA zone instead of
    // a regional alias (bun's V8 uses "Asia/Calcutta" not "Asia/Kolkata").
    fireEvent.change(select, { target: { value: 'America/New_York' } });
    expect(captured).toBe('America/New_York');
  });

  test('includes a non-IANA `value` as a leading option so the current selection always renders', () => {
    // Some legacy rounds saved abbreviations like "PST" before the IANA
    // select shipped — the picker must still display them so the recruiter
    // can re-pick a valid zone instead of seeing a blank field.
    render(<TimezoneSelect id="tz" value="LegacyZoneName" onChange={noop} />);
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    expect(select.value).toBe('LegacyZoneName');
    // Option for the legacy value is present.
    const opts = Array.from(select.options).map((o) => o.value);
    expect(opts).toContain('LegacyZoneName');
  });

  test('IANA option list contains the common zones the recruiter dropdown promised', () => {
    render(<TimezoneSelect id="tz" value="UTC" onChange={noop} />);
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    const opts = Array.from(select.options).map((o) => o.value);
    // Spot-check the zones the v1 component explicitly listed. Note bun's
    // V8 uses the legacy "Asia/Calcutta" name rather than "Asia/Kolkata";
    // we just need an India option present, not the specific spelling.
    for (const tz of [
      'UTC',
      'America/New_York',
      'America/Los_Angeles',
      'Europe/London',
      'Asia/Tokyo',
      'Australia/Sydney',
    ]) {
      expect(opts).toContain(tz);
    }
    expect(
      opts.some((o) => o === 'Asia/Kolkata' || o === 'Asia/Calcutta'),
    ).toBe(true);
  });

  test('option labels include an offset suffix so the recruiter can see GMT-X', () => {
    render(<TimezoneSelect id="tz" value="UTC" onChange={noop} />);
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    const nyOpt = Array.from(select.options).find(
      (o) => o.value === 'America/New_York',
    );
    // Label is `New York (GMT-X) — America` (exact offset depends on DST).
    expect(nyOpt?.textContent).toMatch(/New York.*GMT/);
  });

  test('appends an additional className when provided', () => {
    render(
      <TimezoneSelect
        id="tz"
        value="UTC"
        onChange={noop}
        className="custom-cls"
      />,
    );
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    expect(select.className).toContain('custom-cls');
  });
});
