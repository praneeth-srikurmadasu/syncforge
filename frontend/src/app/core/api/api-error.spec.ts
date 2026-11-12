import { HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { ApiError } from './api-error';

describe('ApiError', () => {
  it('reads the backend error envelope', () => {
    const error = ApiError.from(
      new HttpErrorResponse({
        status: 412,
        error: {
          error: {
            code: 'version_conflict',
            message: 'The employee was changed by someone else.',
            details: { current_version: 4 },
            request_id: 'req-1',
          },
        },
      }),
    );
    expect(error.status).toBe(412);
    expect(error.code).toBe('version_conflict');
    expect(error.message).toBe('The employee was changed by someone else.');
    expect(error.requestId).toBe('req-1');
  });

  it('maps a network failure to a clear message', () => {
    const error = ApiError.from(new HttpErrorResponse({ status: 0 }));
    expect(error.isNetwork).toBe(true);
    expect(error.code).toBe('network_error');
  });

  it('keeps the X-Request-ID header when the body is not an envelope', () => {
    const error = ApiError.from(
      new HttpErrorResponse({
        status: 502,
        statusText: 'Bad Gateway',
        headers: new HttpHeaders({ 'X-Request-ID': 'abc' }),
        error: '<html>proxy error</html>',
      }),
    );
    expect(error.code).toBe('api_unreachable');
    expect(error.requestId).toBe('abc');
  });

  it('extracts field issues from a validation error', () => {
    const error = new ApiError(
      422,
      'validation_error',
      'Request validation failed.',
      [
        { field: 'email', message: 'value is not a valid email address', type: 'value_error' },
        { field: 'query.limit', message: 'too large', type: 'less_than_equal' },
      ],
      'r',
    );
    expect(error.fieldIssues).toEqual([
      { field: 'email', message: 'value is not a valid email address' },
      { field: 'limit', message: 'too large' },
    ]);
  });

  it('explains a gateway error that did not come from the API', () => {
    const error = ApiError.from(
      new HttpErrorResponse({ status: 502, statusText: 'Bad Gateway', error: 'proxy error' }),
    );
    expect(error.code).toBe('api_unreachable');
    expect(error.isNetwork).toBe(true);
    expect(error.message).toContain('not responding');
  });

  it('keeps a connector failure reported by the API as a 502 with its envelope', () => {
    const error = ApiError.from(
      new HttpErrorResponse({
        status: 502,
        error: {
          error: {
            code: 'connector_error',
            message: 'Slack failed.',
            details: null,
            request_id: 'r',
          },
        },
      }),
    );
    expect(error.code).toBe('connector_error');
    expect(error.isNetwork).toBe(false);
  });

  it('returns the same instance when given an ApiError', () => {
    const original = new ApiError(404, 'not_found', 'Missing', null, null);
    expect(ApiError.from(original)).toBe(original);
  });
});
