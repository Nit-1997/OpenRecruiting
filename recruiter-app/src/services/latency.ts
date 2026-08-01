import { ServiceError } from './service-error';

declare global {
  interface Window {
    __FAIL_RATE?: number;
    __LATENCY_MS?: number;
  }
}

const DEFAULT_LATENCY_RANGE: [number, number] = [120, 250];

export async function simulate(): Promise<void> {
  const override = typeof window !== 'undefined' ? window.__LATENCY_MS : undefined;
  const delay =
    override !== undefined
      ? override
      : DEFAULT_LATENCY_RANGE[0] +
        Math.random() * (DEFAULT_LATENCY_RANGE[1] - DEFAULT_LATENCY_RANGE[0]);
  if (delay > 0) await new Promise((r) => setTimeout(r, delay));
  maybeFail();
}

function maybeFail(): void {
  const rate = typeof window !== 'undefined' ? (window.__FAIL_RATE ?? 0) : 0;
  if (rate > 0 && Math.random() < rate) {
    throw new ServiceError('network', 'Injected failure for QA');
  }
}
