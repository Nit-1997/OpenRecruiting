import { describe, expect, mock, test } from 'bun:test';
import { render, screen } from '@testing-library/react';
import AppError from '../error';
import NotFound from '../not-found';

describe('app/error.tsx', () => {
  test('renders the branded recovery UI for a thrown error', () => {
    const error = new Error('boom') as Error & { digest?: string };
    render(<AppError error={error} reset={() => {}} />);

    // Branded heading + an accessible recovery region.
    expect(screen.getByRole('heading', { name: /something went wrong/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /try again/i })).toBeTruthy();
  });

  test('the "Try again" button calls the reset prop', () => {
    const reset = mock(() => {});
    const error = new Error('boom') as Error & { digest?: string };
    render(<AppError error={error} reset={reset} />);

    const button = screen.getByRole('button', { name: /try again/i }) as HTMLButtonElement;
    button.click();

    expect(reset).toHaveBeenCalledTimes(1);
  });
});

describe('app/not-found.tsx', () => {
  test('renders the branded 404 with a link back to the app home', () => {
    render(<NotFound />);

    expect(screen.getByRole('heading', { name: /404|not found/i })).toBeTruthy();

    const homeLink = screen.getByRole('link', {
      name: /home|dashboard|back/i,
    }) as HTMLAnchorElement;
    expect(homeLink).toBeTruthy();
    expect(homeLink.getAttribute('href')).toBe('/');
  });
});
