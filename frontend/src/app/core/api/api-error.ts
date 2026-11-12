import { HttpErrorResponse } from '@angular/common/http';

/** Field-level problem reported by the API's validation errors (422). */
export interface FieldIssue {
  field: string;
  message: string;
}

/**
 * The one error type the application deals with. Built from the backend's envelope
 * `{"error": {code, message, details, request_id}}`; network failures and unexpected
 * bodies are mapped too, so nothing reaches a component as a raw HttpErrorResponse.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: unknown,
    readonly requestId: string | null,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  get isNetwork(): boolean {
    return this.status === 0;
  }

  /** Field issues from a 422 response: `details` is `[{field, message, type}]`. */
  get fieldIssues(): FieldIssue[] {
    if (!Array.isArray(this.details)) return [];
    return this.details.flatMap((d) => {
      const issue = d as { field?: unknown; message?: unknown };
      return typeof issue.field === 'string' && typeof issue.message === 'string'
        ? [{ field: issue.field.replace(/^(query|path|header)\./, ''), message: issue.message }]
        : [];
    });
  }

  static from(error: unknown): ApiError {
    if (error instanceof ApiError) return error;
    if (error instanceof HttpErrorResponse) {
      const requestId = error.headers?.get('X-Request-ID') ?? null;
      if (error.status === 0) {
        return new ApiError(
          0,
          'network_error',
          'The SyncForge API could not be reached. Check that the backend is running.',
          null,
          null,
        );
      }
      const envelope = (error.error as { error?: Record<string, unknown> } | null)?.error;
      if (envelope && typeof envelope['message'] === 'string') {
        return new ApiError(
          error.status,
          String(envelope['code'] ?? 'error'),
          envelope['message'],
          envelope['details'] ?? null,
          (envelope['request_id'] as string | undefined) ?? requestId,
        );
      }
      return new ApiError(
        error.status,
        `http_${error.status}`,
        error.statusText ? `${error.status} ${error.statusText}` : `HTTP ${error.status}`,
        null,
        requestId,
      );
    }
    const message = error instanceof Error ? error.message : 'Unexpected error';
    return new ApiError(-1, 'client_error', message, null, null);
  }
}
