import { Injectable, signal } from '@angular/core';
import { ApiError } from '../api/api-error';

export type ToastKind = 'success' | 'error' | 'info';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  requestId?: string | null;
}

/** Short-lived notifications for the result of an action. */
@Injectable({ providedIn: 'root' })
export class ToastService {
  private nextId = 1;
  readonly toasts = signal<Toast[]>([]);

  success(message: string): void {
    this.push({ kind: 'success', message });
  }

  info(message: string): void {
    this.push({ kind: 'info', message });
  }

  /** Shows the API's message and request ID, so the failure can be traced in the logs. */
  error(error: unknown, prefix?: string): void {
    const apiError = ApiError.from(error);
    const message = prefix ? `${prefix}: ${apiError.message}` : apiError.message;
    this.push({ kind: 'error', message, requestId: apiError.requestId }, 9000);
  }

  dismiss(id: number): void {
    this.toasts.update((list) => list.filter((t) => t.id !== id));
  }

  private push(toast: Omit<Toast, 'id'>, duration = 4500): void {
    const id = this.nextId++;
    this.toasts.update((list) => [...list.slice(-3), { ...toast, id }]);
    setTimeout(() => this.dismiss(id), duration);
  }
}
