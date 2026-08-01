import { afterEach, describe, expect, test } from 'bun:test';
import { clearAllListeners, emit, on } from '../events';

afterEach(() => clearAllListeners());

describe('service events bus', () => {
  test('fires registered listeners with payload', () => {
    const seen: unknown[] = [];
    on('requisition:created', (p) => seen.push(p));
    emit('requisition:created', { id: 'req_1' });
    expect(seen).toEqual([{ id: 'req_1' }]);
  });

  test('unsubscribe removes listener', () => {
    let count = 0;
    const off = on('candidate:created', () => count++);
    emit('candidate:created');
    off();
    emit('candidate:created');
    expect(count).toBe(1);
  });

  test('independent listeners for independent events', () => {
    let a = 0;
    let b = 0;
    on('round:created', () => a++);
    on('round:updated', () => b++);
    emit('round:created');
    emit('round:updated');
    emit('round:updated');
    expect(a).toBe(1);
    expect(b).toBe(2);
  });
});
