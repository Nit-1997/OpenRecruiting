import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, render } from '@testing-library/react';
import {
  IntakeHubSkeleton,
  PacketPaneSkeleton,
  PipelineSkeleton,
  RoleDetailSkeleton,
  RolesTableSkeleton,
  SettingsCardSkeleton,
} from './index';

afterEach(cleanup);

describe('skeletons render with their root id and shimmer cells', () => {
  test('RolesTableSkeleton renders requested rows', () => {
    const { container } = render(<RolesTableSkeleton id="sk-roles" rows={4} />);
    expect(container.querySelector('#sk-roles')).not.toBeNull();
    expect(container.querySelectorAll('#sk-roles > [id^="sk-roles-row-"]').length).toBe(4);
    expect(container.querySelector('.mz-skeleton')).not.toBeNull();
  });

  test('each skeleton mounts under its id', () => {
    for (const [Comp, id] of [
      [RoleDetailSkeleton, 'sk-rd'],
      [PipelineSkeleton, 'sk-pl'],
      [PacketPaneSkeleton, 'sk-pk'],
      [SettingsCardSkeleton, 'sk-set'],
      [IntakeHubSkeleton, 'sk-hub'],
    ] as const) {
      const { container, unmount } = render(<Comp id={id} />);
      expect(container.querySelector(`#${id}`)).not.toBeNull();
      expect(container.querySelector('.mz-skeleton')).not.toBeNull();
      unmount();
    }
  });
});
