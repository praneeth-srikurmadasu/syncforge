import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { AuthApi } from '../../core/api/auth.api';
import { OwnSecurityEvent } from '../../core/api/models';
import { BadgeComponent, Tone } from '../../shared/ui/badge.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';

const EVENTS: Record<string, { label: string; tone: Tone }> = {
  login_succeeded: { label: 'Signed in', tone: 'success' },
  login_failed: { label: 'Failed sign-in', tone: 'danger' },
  login_rate_limited: { label: 'Sign-in blocked', tone: 'warning' },
  logout: { label: 'Signed out', tone: 'neutral' },
  registered: { label: 'Account created', tone: 'info' },
  registration_rate_limited: { label: 'Registration blocked', tone: 'warning' },
};

const REASONS: Record<string, string> = {
  wrong_password: 'wrong password',
  inactive_user: 'account disabled',
  login_failures: 'too many failed attempts',
  login_ip: 'too many attempts from this network',
};

/** "Chrome on Windows" from a user-agent string; the raw value when it is not recognized. */
export function describeUserAgent(ua: string | null | undefined): string {
  if (!ua) return 'Unknown';
  const browser = /Edg\//.test(ua)
    ? 'Edge'
    : /OPR\//.test(ua)
      ? 'Opera'
      : /Firefox\//.test(ua)
        ? 'Firefox'
        : /Chrome\//.test(ua)
          ? 'Chrome'
          : /Safari\//.test(ua)
            ? 'Safari'
            : null;
  const os = /Windows/.test(ua)
    ? 'Windows'
    : /Android/.test(ua)
      ? 'Android'
      : /iPhone|iPad/.test(ua)
        ? 'iOS'
        : /Mac OS X/.test(ua)
          ? 'macOS'
          : /Linux/.test(ua)
            ? 'Linux'
            : null;
  if (browser && os) return `${browser} on ${os}`;
  if (browser || os) return (browser ?? os) as string;
  return ua.length > 60 ? `${ua.slice(0, 60)}…` : ua;
}

/** The signed-in user's own security events from GET /auth/activity. */
@Component({
  selector: 'sf-recent-sign-ins',
  imports: [
    BadgeComponent,
    TimeComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="sf-card">
      <div class="sf-card__header">
        <h2 class="sf-card__title">Recent sign-ins</h2>
        <button type="button" class="sf-btn sf-btn--ghost sf-btn--sm" (click)="activity.reload()">
          Refresh
        </button>
      </div>
      @if (activity.error(); as err) {
        <sf-error-state [error]="err" (retry)="activity.reload()" />
      } @else if (activity.value(); as events) {
        @if (events.length === 0) {
          <sf-empty-state icon="shield" title="No sign-in activity recorded yet" />
        } @else {
          <div class="sf-table-wrap">
            <table class="sf-table">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">What</th>
                  <th scope="col">From</th>
                  <th scope="col">Browser</th>
                </tr>
              </thead>
              <tbody>
                @for (e of events; track e.id) {
                  <tr>
                    <td><sf-time [value]="e.created_at" /></td>
                    <td>
                      <sf-badge [tone]="label(e).tone">{{ label(e).label }}</sf-badge>
                      @if (e.reason && reasons[e.reason]) {
                        <span class="sf-muted reason">{{ reasons[e.reason] }}</span>
                      }
                    </td>
                    <td class="sf-mono">{{ e.client_ip ?? '-' }}</td>
                    <td [attr.title]="e.user_agent">{{ describe(e.user_agent) }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          <p class="sf-faint note">
            The last {{ events.length }} events for your account. If you see a sign-in you do not
            recognize, tell your administrator.
          </p>
        }
      } @else {
        <div class="sf-card__body"><sf-skeleton [rows]="3" /></div>
      }
    </section>
  `,
  styles: `
    .reason {
      margin-left: var(--sf-space-2);
      font-size: var(--sf-text-sm);
    }
    .note {
      margin: 0;
      padding: var(--sf-space-3) var(--sf-space-4);
      font-size: var(--sf-text-xs);
    }
  `,
})
export class RecentSignInsComponent {
  private readonly api = inject(AuthApi);
  protected readonly reasons = REASONS;
  protected readonly describe = describeUserAgent;
  protected readonly activity = httpResource<OwnSecurityEvent[]>(() =>
    this.api.activityRequest(10),
  );

  protected label(e: OwnSecurityEvent): { label: string; tone: Tone } {
    return EVENTS[e.event] ?? { label: e.event, tone: 'neutral' };
  }
}
