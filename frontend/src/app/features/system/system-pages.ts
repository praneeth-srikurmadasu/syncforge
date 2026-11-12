import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { OrgContextService } from '../../core/org/org-context.service';
import { EmptyStateComponent } from '../../shared/ui/states.component';

/** Organization could not be opened: not a member (API 404) or the request failed. */
@Component({
  selector: 'sf-unavailable',
  imports: [EmptyStateComponent, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <sf-empty-state
      [icon]="reason() === 'not_found' ? 'shield-alert' : 'circle-alert'"
      [title]="
        reason() === 'not_found' ? 'Organization not available' : 'Organization could not be loaded'
      "
      [message]="message()"
    >
      <a class="sf-btn" routerLink="/">Go to my organizations</a>
    </sf-empty-state>
  `,
  styles: `
    :host {
      display: grid;
      place-items: center;
      min-height: 100vh;
    }
  `,
})
export class UnavailableComponent {
  private readonly org = inject(OrgContextService);
  protected readonly reason = toSignal(
    inject(ActivatedRoute).queryParamMap.pipe(map((p) => p.get('reason'))),
  );
  protected readonly message = computed(() =>
    this.reason() === 'not_found'
      ? 'It does not exist or you are not a member of it. An administrator of the organization can add you.'
      : (this.org.lastError()?.message ?? 'The API did not respond.'),
  );
}

/** A screen the current role cannot use (the API would refuse it with 403). */
@Component({
  selector: 'sf-forbidden',
  imports: [EmptyStateComponent, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="sf-page">
      <sf-empty-state
        icon="shield-alert"
        title="Your role does not include this area"
        message="Ask an organization administrator if you need access."
      >
        <a class="sf-btn" [routerLink]="['/o', org.orgId(), 'dashboard']">Back to the dashboard</a>
      </sf-empty-state>
    </div>
  `,
})
export class ForbiddenComponent {
  protected readonly org = inject(OrgContextService);
}

@Component({
  selector: 'sf-not-found',
  imports: [EmptyStateComponent, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="sf-page">
      <sf-empty-state
        icon="search"
        title="Page not found"
        message="This address does not match any page."
      >
        <a class="sf-btn" routerLink="/">Go home</a>
      </sf-empty-state>
    </div>
  `,
})
export class NotFoundComponent {}
