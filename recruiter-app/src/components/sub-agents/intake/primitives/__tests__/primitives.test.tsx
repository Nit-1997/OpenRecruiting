import { describe, expect, it } from 'bun:test';
import { render } from '@testing-library/react';
import { Orb } from '../orb';
import { ProgressRing } from '../progress-ring';
import { StatusMark } from '../status-mark';

describe('intake primitives', () => {
  it('Orb renders with state', () => {
    const { container } = render(<Orb size={104} state="listening" motion />);
    expect(container.querySelector('.mz-orb')).toBeTruthy();
  });
  it('ProgressRing renders value/total', () => {
    const { getByText } = render(<ProgressRing value={5} total={9} size={60} />);
    expect(getByText('5')).toBeTruthy();
  });
  it('StatusMark renders validated check', () => {
    const { container } = render(<StatusMark status="validated" size={20} />);
    expect(container.firstChild).toBeTruthy();
  });
});
