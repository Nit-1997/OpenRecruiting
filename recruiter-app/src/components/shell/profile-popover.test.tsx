import { describe, expect, test } from 'bun:test';
import { render, screen } from '@testing-library/react';
import { ProfilePopover } from './profile-popover';

describe('ProfilePopover', () => {
  test('renders nothing when closed', () => {
    render(<ProfilePopover id="pop" open={false} onClose={() => {}} />);
    expect(screen.queryByRole('menu')).toBeNull();
  });

  test('renders menuitems for each settings tab plus logout', () => {
    render(<ProfilePopover id="pop" open={true} onClose={() => {}} />);
    const menu = screen.getByRole('menu');
    expect(menu).toBeDefined();
    const items = screen.getAllByRole('menuitem');
    // profile, team, billing, logout — integrations + notifications were
    // moved out of the popover into the standalone /view/integrations rail.
    expect(items.length).toBe(4);
  });

  test('clicking a settings menuitem calls onClose and onOpenSettings with its tab', () => {
    let closed = 0;
    let opened = '';
    render(
      <ProfilePopover
        id="pop"
        open={true}
        onClose={() => {
          closed += 1;
        }}
        onOpenSettings={(tab) => {
          opened = tab;
        }}
      />,
    );
    const billing = document.getElementById('pop-billing');
    billing?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(closed).toBeGreaterThan(0);
    expect(opened).toBe('billing');
  });
});
