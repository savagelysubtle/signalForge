/**
 * Lightweight cross-view sync for feedback data (decisions, outcomes).
 *
 * When either the FeedbackTab or InsightsView mutates feedback data,
 * it calls `notifyFeedbackChanged()`. Any component that called
 * `useFeedbackSync(callback)` will re-fetch its data in response.
 *
 * Uses DOM CustomEvent so no external dependencies are needed and
 * the mechanism works across any component tree without shared context.
 */

const EVENT_NAME = "signalforge:feedback-changed";

export function notifyFeedbackChanged(): void {
  window.dispatchEvent(new CustomEvent(EVENT_NAME));
}

import { useEffect, useRef } from "react";

/**
 * Subscribe to feedback change events. The callback fires whenever
 * another component calls `notifyFeedbackChanged()`.
 *
 * The callback is NOT invoked by the component's own notifications —
 * use a `skipNextRef` pattern if needed, or simply let the re-fetch
 * happen (it's idempotent since the data just changed).
 */
export function useFeedbackSync(onChanged: () => void): void {
  const callbackRef = useRef(onChanged);
  callbackRef.current = onChanged;

  useEffect(() => {
    const handler = () => callbackRef.current();
    window.addEventListener(EVENT_NAME, handler);
    return () => window.removeEventListener(EVENT_NAME, handler);
  }, []);
}
