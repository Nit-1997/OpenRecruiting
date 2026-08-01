import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { LocationAutocomplete } from '../location-autocomplete';

afterEach(cleanup);

function photonResp(features: unknown[]) {
  return { ok: true, json: async () => ({ features }) };
}

describe('LocationAutocomplete', () => {
  it('shows Photon suggestions and emits the formatted label on select', async () => {
    const fetchMock = mock(async () =>
      photonResp([
        { properties: { name: 'San Francisco', state: 'California', country: 'United States' } },
      ]),
    );
    (global as unknown as { fetch: unknown }).fetch = fetchMock;

    const onChange = mock();
    render(<LocationAutocomplete id="loc" value="" onChange={onChange} placeholder="Location" />);

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'San Fr' } });
    const option = await screen.findByText('San Francisco, California, United States');
    fireEvent.mouseDown(option);

    expect(onChange).toHaveBeenCalledWith('San Francisco, California, United States');
  });

  it('passes free text up immediately (keeps "Remote · US" valid)', () => {
    (global as unknown as { fetch: unknown }).fetch = mock(async () => photonResp([]));
    const onChange = mock();
    render(<LocationAutocomplete id="loc2" value="" onChange={onChange} />);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Remote' } });
    expect(onChange).toHaveBeenCalledWith('Remote');
  });
});
