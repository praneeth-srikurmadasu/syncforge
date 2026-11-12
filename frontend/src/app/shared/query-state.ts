import { inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Params, Router } from '@angular/router';

/**
 * List filters live in the URL query string, so a filtered view can be shared, survives a
 * reload and works with the browser's back button.
 */
export function useQueryState() {
  const route = inject(ActivatedRoute);
  const router = inject(Router);
  const params = toSignal(route.queryParamMap, { initialValue: route.snapshot.queryParamMap });

  return {
    params,
    get(name: string): string {
      return params().get(name) ?? '';
    },
    number(name: string, fallback = 0): number {
      const value = Number(params().get(name));
      return Number.isFinite(value) && value >= 0 ? value : fallback;
    },
    /** Merges the change into the URL; empty values are removed. Resets paging unless given. */
    set(patch: Params, resetOffset = true): void {
      const queryParams: Params = { ...patch };
      for (const key of Object.keys(queryParams)) {
        if (queryParams[key] === '' || queryParams[key] === false) queryParams[key] = null;
      }
      if (resetOffset && !('offset' in patch)) queryParams['offset'] = null;
      void router.navigate([], {
        relativeTo: route,
        queryParams,
        queryParamsHandling: 'merge',
        replaceUrl: true,
      });
    },
    clear(): void {
      void router.navigate([], { relativeTo: route, queryParams: {}, replaceUrl: true });
    },
  };
}
