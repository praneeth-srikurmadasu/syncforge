import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ApiError } from '../../core/api/api-error';
import { DashboardData, Overview, dayWindows } from './dashboard-data';

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

  it('reads every figure from one summary request', () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const data = TestBed.inject(DashboardData);
    const http = TestBed.inject(HttpTestingController);
    let overview: Overview | undefined;
    data.overview('o1').subscribe((o) => (overview = o));
    http.expectOne('/api/v1/organizations/o1/summary').flush({
      generated_at: '2026-11-12T12:00:00Z',
      employees: { active: 14, on_leave: 1, terminated: 2 },
      workflows: { active: 1, total: 2 },
      connectors: { connected: 1, total: 1 },
      events: { pending: 0, processing: 0, retrying: 1, completed: 30, dead_letter: 2 },
      dead_letters_open: 2,
      conflicts_open: { low: 0, medium: 1, high: 0, critical: 0, total: 1 },
      processing: {
        window_hours: 24,
        completed: 30,
        end_to_end_seconds: { p50: 0.4, p95: 3, max: 9 },
        processing_seconds: { p50: 0.1, p95: 0.2, max: 0.4 },
      },
    });
    http
      .expectOne((r) => r.url === '/api/v1/organizations/o1/connectors')
      .flush({ items: [], total: 0, limit: 100, offset: 0 });
    http.verify(); // no other requests: the summary replaced ~18 list calls

    expect(overview?.employeesActive).toBe(14);
    expect(overview?.events.dead_letter).toBe(2);
    expect(overview?.conflictsBySeverity.medium).toBe(1);
    expect(overview?.processing).toMatchObject({ completed: 30 });
  });

  it('shows a failed summary as an error on each figure instead of zero', () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const data = TestBed.inject(DashboardData);
    const http = TestBed.inject(HttpTestingController);
    let overview: Overview | undefined;
    data.overview('o1').subscribe((o) => (overview = o));
    http
      .expectOne('/api/v1/organizations/o1/summary')
      .flush(
        { error: { code: 'x', message: 'boom', details: null, request_id: 'r' } },
        { status: 500, statusText: 'Server Error' },
      );
    http
      .expectOne((r) => r.url === '/api/v1/organizations/o1/connectors')
      .flush({ items: [], total: 0, limit: 100, offset: 0 });
    expect(overview?.deadLettersOpen).toBeInstanceOf(ApiError);
    expect(overview?.employeesActive).toBeInstanceOf(ApiError);
    expect(overview?.connectors).toEqual([]);
    http.verify();
  });
});
