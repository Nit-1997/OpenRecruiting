// FE coverage for the candidate SCREENING call provider.
//
// The offer-URL builder is the load-bearing bit (it picks local/prod/override and
// must always target /api/offer/screening/{token}); it's exported expressly so we
// can assert it without standing up a real WebRTC transport. We also smoke-test
// that the provider renders + exposes empty transcript state before any call,
// mirroring feedback-call-provider.test.tsx.

import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { cleanup, render } from '@testing-library/react';
import {
  getScreeningOfferUrl,
  ScreeningCallProvider,
  useScreeningCall,
} from './screening-call-provider';

afterEach(cleanup);

function Probe() {
  const call = useScreeningCall();
  return (
    <div>
      <span id="probe-status">{call.status}</span>
      <span id="probe-turns">{call.transcript.length}</span>
      <span id="probe-interim">{`[${call.botInterim}]`}</span>
    </div>
  );
}

describe('getScreeningOfferUrl', () => {
  const ORIGINAL_OVERRIDE = process.env.NEXT_PUBLIC_SCREENING_VOICE_OFFER_URL;
  const realLocation = window.location;

  function setHostname(hostname: string) {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...realLocation, hostname, protocol: 'https:' },
    });
  }

  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_SCREENING_VOICE_OFFER_URL;
  });

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: realLocation,
    });
    if (ORIGINAL_OVERRIDE === undefined) {
      delete process.env.NEXT_PUBLIC_SCREENING_VOICE_OFFER_URL;
    } else {
      process.env.NEXT_PUBLIC_SCREENING_VOICE_OFFER_URL = ORIGINAL_OVERRIDE;
    }
  });

  test('localhost resolves to the local voice agent on :8011', () => {
    setHostname('localhost');
    expect(getScreeningOfferUrl('tok-1')).toBe('http://127.0.0.1:8011/api/offer/screening/tok-1');
  });

  test('127.0.0.1 resolves to the local voice agent on :8011', () => {
    setHostname('127.0.0.1');
    expect(getScreeningOfferUrl('tok-1')).toBe('http://127.0.0.1:8011/api/offer/screening/tok-1');
  });

  test('a deployed host resolves to the same-origin voice proxy', () => {
    setHostname('recruiting.example.com');
    expect(getScreeningOfferUrl('tok-2')).toBe(
      'https://recruiting.example.com/voice-ws-v2/api/offer/screening/tok-2',
    );
  });

  test('NEXT_PUBLIC_SCREENING_VOICE_OFFER_URL override wins and keeps the screening path', () => {
    process.env.NEXT_PUBLIC_SCREENING_VOICE_OFFER_URL =
      'https://staging.example.com/api/offer/screening';
    setHostname('localhost:3005');
    expect(getScreeningOfferUrl('tok-3')).toBe(
      'https://staging.example.com/api/offer/screening/tok-3',
    );
  });

  test('override trailing slash is normalized', () => {
    process.env.NEXT_PUBLIC_SCREENING_VOICE_OFFER_URL =
      'https://staging.example.com/api/offer/screening/';
    setHostname('localhost');
    expect(getScreeningOfferUrl('tok-4')).toBe(
      'https://staging.example.com/api/offer/screening/tok-4',
    );
  });

  test('the token is URL-encoded into the path', () => {
    setHostname('localhost');
    expect(getScreeningOfferUrl('a b/c')).toBe(
      'http://127.0.0.1:8011/api/offer/screening/a%20b%2Fc',
    );
  });
});

describe('ScreeningCallProvider', () => {
  test('exposes idle status + empty transcript before any call', () => {
    const { container } = render(
      <ScreeningCallProvider>
        <Probe />
      </ScreeningCallProvider>,
    );
    expect(container.querySelector('#probe-status')?.textContent).toBe('idle');
    expect(container.querySelector('#probe-turns')?.textContent).toBe('0');
    expect(container.querySelector('#probe-interim')?.textContent).toBe('[]');
  });
});
