import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiError } from '../../core/api/api-error';
import { ConnectorsApi } from '../../core/api/integrations.api';
import { ConflictDetail, Connector, Member, Page, ResolveRequest } from '../../core/api/models';
import { ConflictsApi } from '../../core/api/operations.api';
import { OrganizationsApi } from '../../core/api/organizations.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { ToastService } from '../../core/toast/toast.service';
import { humanize } from '../../core/util/format';
import { BadgeComponent, StatusBadgeComponent } from '../../shared/ui/badge.component';
import { EmployeeNameComponent } from '../../shared/ui/employee-name.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { ErrorStateComponent, SkeletonComponent } from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';
import { fieldLabel } from './conflict-fields';

type Choice = ResolveRequest['resolution'];

@Component({
  selector: 'sf-conflict-detail',
  imports: [
    FormsModule,
    RouterLink,
    PageHeaderComponent,
    BadgeComponent,
    StatusBadgeComponent,
    EmployeeNameComponent,
    IconComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './conflict-detail.component.html',
  styleUrl: './conflict-detail.component.scss',
})
export class ConflictDetailComponent {
  readonly id = input.required<string>();

  protected readonly org = inject(OrgContextService);
  private readonly api = inject(ConflictsApi);
  private readonly connectorsApi = inject(ConnectorsApi);
  private readonly orgApi = inject(OrganizationsApi);
  private readonly toast = inject(ToastService);
  protected readonly humanize = humanize;

  /** History wording for the API's resolution values. */
  protected resolutionLabel(resolution: string): string {
    const labels: Record<string, string> = {
      use_syncforge: "Kept SyncForge's value",
      use_external: "Used the application's value",
      dismiss: 'Dismissed',
    };
    return labels[resolution] ?? humanize(resolution);
  }
  protected readonly fieldLabel = fieldLabel;

  protected readonly conflict = httpResource<ConflictDetail>(() =>
    this.api.getRequest(this.org.orgId(), this.id()),
  );
  private readonly connectors = httpResource<Page<Connector>>(() =>
    this.connectorsApi.listRequest(this.org.orgId()),
  );
  private readonly members = httpResource<Page<Member>>(() =>
    this.orgApi.membersRequest(this.org.orgId(), { limit: 100 }),
  );

  protected readonly connectorName = computed(() => {
    const c = this.conflict.value();
    const list = this.connectors.value()?.items ?? [];
    return (c && list.find((x) => x.id === c.connector_id)?.name) ?? 'the application';
  });
  protected readonly memberNames = computed(
    () => new Map((this.members.value()?.items ?? []).map((m) => [m.user_id, m.full_name])),
  );

  /** The resolution the policy points to. */
  protected readonly recommended = computed<Choice>(() =>
    this.conflict.value()?.authoritative_source === 'connector' ? 'use_external' : 'use_syncforge',
  );

  protected readonly choice = signal<Choice | null>(null);
  protected override = false;
  protected note = '';
  protected readonly busy = signal(false);
  protected readonly error = signal<ApiError | null>(null);

  protected readonly againstPolicy = computed(() => {
    const c = this.choice();
    return c !== null && c !== 'dismiss' && c !== this.recommended();
  });
  protected readonly needsNote = computed(
    () => this.choice() === 'dismiss' || this.againstPolicy(),
  );
  /** Adopting a value into the employee record needs employees:write (except account status). */
  protected readonly lacksEmployeeWrite = computed(
    () =>
      this.choice() === 'use_external' &&
      this.conflict.value()?.field !== 'account_active' &&
      !this.org.can('employees:write'),
  );

  protected select(choice: Choice): void {
    this.choice.set(choice);
    this.error.set(null);
    this.override = false;
  }

  protected canSubmit(): boolean {
    if (!this.choice() || this.busy() || this.lacksEmployeeWrite()) return false;
    if (this.needsNote() && !this.note.trim()) return false;
    if (this.againstPolicy() && !this.override) return false;
    return true;
  }

  protected resolve(c: ConflictDetail): void {
    const choice = this.choice();
    if (!choice || !this.canSubmit()) return;
    this.busy.set(true);
    this.error.set(null);
    const body: ResolveRequest = {
      resolution: choice,
      override: this.againstPolicy() ? true : false,
      note: this.note.trim() || null,
    };
    this.api.resolve(this.org.orgId(), c.id, body).subscribe({
      next: (updated) => {
        this.busy.set(false);
        this.conflict.set(updated);
        this.choice.set(null);
        this.note = '';
        this.toast.success(choice === 'dismiss' ? 'Conflict dismissed' : 'Conflict resolved');
      },
      error: (e: unknown) => {
        this.busy.set(false);
        this.error.set(ApiError.from(e));
      },
    });
  }

  protected resolverName(userId: string | null): string {
    if (!userId) return 'the system';
    return this.memberNames().get(userId) ?? 'a former member';
  }
}
