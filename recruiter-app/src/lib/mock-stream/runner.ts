import { delayForEvent } from './timings';
import type { StreamEvent, StreamScript } from './types';

export interface MockStreamOptions {
  speed?: number;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function* createMockStream(
  script: StreamScript,
  options: MockStreamOptions = {},
): AsyncIterable<StreamEvent> {
  const speed = options.speed ?? 1;
  for (const ev of script) {
    const delay = delayForEvent(ev.type) * speed;
    if (delay > 0) await sleep(delay);
    yield ev;
  }
}
