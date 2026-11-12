import { DestroyRef, effect, inject, signal } from '@angular/core';

/**
 * Re-runs `reload` every `seconds` while switched on and the tab is visible. Polling the
 * list endpoints is how screens follow background processing: the API has no push channel.
 */
export function useAutoRefresh(reload: () => void, seconds = 5) {
  const enabled = signal(false);
  let timer: ReturnType<typeof setInterval> | null = null;
  const stop = () => {
    if (timer) clearInterval(timer);
    timer = null;
  };
  effect(() => {
    stop();
    if (enabled()) {
      timer = setInterval(() => {
        if (document.visibilityState === 'visible') reload();
      }, seconds * 1000);
    }
  });
  inject(DestroyRef).onDestroy(stop);
  return { enabled, seconds };
}
