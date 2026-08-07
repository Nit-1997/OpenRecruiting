// Tests that clicking a transcript segment fires onSeek with the correct
// start_seconds value. This covers Bug #21: transcript clicks must scrub
// the video to the right timestamp.

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

// --- mock heavy imports drawer.tsx pulls in at module level -----------------

mock.module('@/hooks/use-services', () => ({
  usePacket: () => ({ data: null, loading: false, error: null }),
  useRecording: () => ({ data: null }),
  useRequisition: () => ({ data: null, loading: false, error: null }),
  useEnsureSeeded: () => {},
}));

// IMPORTANT: bun's `mock.module` is process-wide. Previously this file
// replaced the entire `@/services` index with empty stubs, which made
// every later test that imported `candidates.create` / `requisitions.list`
// etc. see `undefined`. The test only mounts a UI component that doesn't
// actually call into `@/services` (use-services is mocked above), so the
// narrowest correct mock is no mock at all.
//
// If a future test in this file needs to control a specific service
// function, mock the SPECIFIC `@/services/<name>` submodule rather than
// the index re-export.

mock.module('@/lib/rounds', () => ({
  isCustomRound: () => false,
}));

// Note: don't mock date-fns-tz here. drawer.tsx no longer imports it (the
// ScheduleModal that did was extracted in Task 6.1). Mocking it would
// pollute other test files via Bun's global mock.module() — see
// schedule-modal.test.tsx which depends on the real formatInTimeZone.

// lucide-react: return lightweight stubs so the icons don't fail
mock.module('lucide-react', () =>
  new Proxy(
    {},
    {
      get: (_t, name) => {
        const Stub = () => null;
        Stub.displayName = String(name);
        return Stub;
      },
    },
  ),
);

// --- import the component under test ----------------------------------------

import { TranscriptViewer } from './drawer';

// ----------------------------------------------------------------------------

afterEach(() => {
  cleanup();
});

describe('TranscriptViewer — transcript segment click scrubs to correct time', () => {
  const segments = [
    { start_seconds: 0, end_seconds: 5, speaker: 'Interviewer', text: 'Tell me about yourself.' },
    { start_seconds: 10, end_seconds: 20, speaker: 'Candidate', text: 'Sure, happy to share.' },
    { start_seconds: 42, end_seconds: 55, speaker: 'Interviewer', text: 'What is your biggest strength?' },
  ];

  it('calls onSeek with start_seconds of the clicked segment', () => {
    const calls: number[] = [];
    render(
      <TranscriptViewer
        id="tv-test"
        segments={segments}
        activeIndex={0}
        onSeek={(t) => calls.push(t)}
      />,
    );

    // Click the second segment (start_seconds = 10)
    fireEvent.click(screen.getByText('Sure, happy to share.'));
    expect(calls).toEqual([10]);
  });

  it('calls onSeek with start_seconds of the third segment', () => {
    const calls: number[] = [];
    render(
      <TranscriptViewer
        id="tv-test-2"
        segments={segments}
        activeIndex={-1}
        onSeek={(t) => calls.push(t)}
      />,
    );

    fireEvent.click(screen.getByText('What is your biggest strength?'));
    expect(calls).toEqual([42]);
  });

  it('fires onSeek even when the segment is the active one', () => {
    const calls: number[] = [];
    render(
      <TranscriptViewer
        id="tv-test-3"
        segments={segments}
        activeIndex={1}
        onSeek={(t) => calls.push(t)}
      />,
    );

    // Click the already-active segment (start_seconds = 10)
    fireEvent.click(screen.getByText('Sure, happy to share.'));
    expect(calls).toEqual([10]);
  });
});
