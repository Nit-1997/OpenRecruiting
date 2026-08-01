"use client";

import { usePostHog } from "posthog-js/react";

export function useAnalytics() {
  const posthog = usePostHog();

  const trackEvent = (eventName: string, properties?: Record<string, unknown>) => {
    posthog?.capture(eventName, properties);
  };

  const identifyUser = (userId: string, properties?: Record<string, unknown>) => {
    posthog?.identify(userId, properties);
  };

  const setUserProperties = (properties: Record<string, unknown>) => {
    posthog?.people.set(properties);
  };

  const setGroupProperties = (groupType: string, groupKey: string, properties?: Record<string, unknown>) => {
    posthog?.group(groupType, groupKey, properties);
  };

  const resetUser = () => {
    posthog?.reset();
  };

  return { trackEvent, identifyUser, setUserProperties, setGroupProperties, resetUser };
}
