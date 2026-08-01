import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, render } from '@testing-library/react';
import { FeedbackCallProvider, useFeedbackCall } from './feedback-call-provider';

afterEach(cleanup);

function Probe() {
  const call = useFeedbackCall();
  return (
    <div>
      <span id="probe-turns">{call.transcript.length}</span>
      <span id="probe-interim">{`[${call.botInterim}]`}</span>
    </div>
  );
}

describe('FeedbackCallProvider transcript state', () => {
  test('exposes empty transcript + interim before any call', () => {
    const { container } = render(
      <FeedbackCallProvider>
        <Probe />
      </FeedbackCallProvider>,
    );
    expect(container.querySelector('#probe-turns')?.textContent).toBe('0');
    expect(container.querySelector('#probe-interim')?.textContent).toBe('[]');
  });
});
