import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ApiError } from '../../core/api/api-error';
import { DashboardData, dayWindows } from './dashboard-data';

describe('DashboardData', () => {
  it('builds consecutive local-day windows ending today', () => {
    const windows = dayWindows(3, new Date(2026, 4, 10, 15, 30));
    expect(windows).toHaveLength(3);
    expect(new Date(windows[2].since).getDate()).toBe(10);
    expect(new Date(windows[0].since).getDate()).toBe(8);
    expect(windows[0].until).toBe(windows[1].since);
  });

  it('reads daily activity from audit-log totals per window', () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const data = TestBed.inject(DashboardData);
    const http = TestBed.inject(HttpTestingController);
    let result: { succeeded: number[]; failed: number[]; retries: number[] } | undefined;
    data.dailyActivity('o1', 2).subscribe((r) => (result = r));

    const requests = http.match((r) => r.url === '/api/v1/organizations/o1/audit-logs');
    expect(requests).toHaveLength(6);
    for (const req of requests) {
      expect(req.request.params.get('limit')).toBe('1');
      const action = req.request.params.get('action');
      const outcome = req.request.params.get('outcome');
      const total = action === 'sync.retry_scheduled' ? 5 : outcome === 'success' ? 3 : 1;
      req.flush({ items: [], total, limit: 1, offset: 0 });
    }
    expect(result?.succeeded).toEqual([3, 3]);
    expect(result?.failed).toEqual([1, 1]);
    expect(result?.retries).toEqual([5, 5]);
    http.verify();
  });

  it('reports a figure that failed to load as an error instead of zero', () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const data = TestBed.inject(DashboardData);
    const http = TestBed.inject(HttpTestingController);
    let overview: Awaited<ReturnType<typeof data.overview>> extends never ? never : unknown;
    data.overview('o1').subscribe((o) => (overview = o));
    for (const req of http.match(() => true)) {
      if (req.request.url.endsWith('/dead-letter-events')) {
        req.flush(
          { error: { code: 'x', message: 'boom', details: null, request_id: 'r' } },
          { status: 500, statusText: 'Server Error' },
        );
      } else if (req.request.url.endsWith('/connectors')) {
        req.flush({ items: [], total: 0, limit: 100, offset: 0 });
      } else {
        req.flush({ items: [], total: 2, limit: 1, offset: 0 });
      }
    }
    const o = overview as { deadLettersOpen: unknown; employeesActive: unknown };
    expect(o.deadLettersOpen).toBeInstanceOf(ApiError);
    expect(o.employeesActive).toBe(2);
    http.verify();
  });
});
