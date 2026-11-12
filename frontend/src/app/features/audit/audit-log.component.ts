import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuditEntry, Member, Page } from '../../core/api/models';
import { AuditApi, AuditQuery } from '../../core/api/operations.api';
import { OrganizationsApi } from '../../core/api/organizations.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { formatDateTime, humanize } from '../../core/util/format';
import { useQueryState } from '../../shared/query-state';
import { StatusBadgeComponent } from '../../shared/ui/badge.component';
import { CopyIdComponent } from '../../shared/ui/copy-id.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { JsonViewComponent } from '../../shared/ui/json-view.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { PaginationComponent } from '../../shared/ui/pagination.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';

/** Resource types written by the backend's audit calls. */
const RESOURCE_TYPES = [
  'employee',
  'department',
  'connector',
  'workflow',
  'integration_event',
  'synchronization_job',
  'dead_letter_event',
  'data_conflict',
  'data_source_policy',
  'membership',
  'organization',
];

/** Action groups for the filter; a value ending in "." matches every action that starts with it. */
const ACTION_GROUPS = [
  { value: 'employee.', label: 'Employees (all)' },
  { value: 'department.', label: 'Departments (all)' },
  { value: 'connector.', label: 'Connectors (all)' },
  { value: 'workflow.', label: 'Workflows (all)' },
  { value: 'workflow.executed', label: 'Workflow executed' },
  { value: 'sync.retry_scheduled', label: 'Retry scheduled' },
  { value: 'event.dead_lettered', label: 'Event dead-lettered' },
  { value: 'dead_letter.replayed', label: 'Dead letter replayed' },
  { value: 'conflict.', label: 'Conflicts (all)' },
  { value: 'data_source_policy.updated', label: 'Policy updated' },
  { value: 'member.', label: 'Members and roles (all)' },
  { value: 'organization.', label: 'Organization (all)' },
];

/** Links from an entry to the screen of the thing it is about, where one exists. */
const RESOURCE_ROUTES: Record<string, string> = {
  employee: 'employees',
  connector: 'connectors',
  workflow: 'workflows',
  integration_event: 'events',
  dead_letter_event: 'dead-letters',
  data_conflict: 'conflicts',
};

@Component({
  selector: 'sf-audit-log',
  imports: [
    RouterLink,
    PageHeaderComponent,
    StatusBadgeComponent,
    CopyIdComponent,
    IconComponent,
    JsonViewComponent,
    PaginationComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './audit-log.component.html',
  styleUrl: './audit-log.component.scss',
})
export class AuditLogComponent {
  protected readonly org = inject(OrgContextService);
  private readonly api = inject(AuditApi);
  private readonly orgApi = inject(OrganizationsApi);
  protected readonly q = useQueryState();
  protected readonly resourceTypes = RESOURCE_TYPES;
  protected readonly actionGroups = ACTION_GROUPS;
  protected readonly humanize = humanize;
  protected readonly formatDateTime = formatDateTime;

  private readonly query = computed<AuditQuery>(() => {
    this.q.params();
    return {
      action: this.q.get('action') || undefined,
      resource_type: this.q.get('resource') || undefined,
      actor_user_id: this.q.get('actor') || undefined,
      outcome: (this.q.get('outcome') as AuditQuery['outcome']) || undefined,
      since: toIso(this.q.get('since')),
      until: toIso(this.q.get('until')),
      limit: 50,
      offset: this.q.number('offset'),
    };
  });
  protected readonly entries = httpResource<Page<AuditEntry>>(() =>
    this.api.listRequest(this.org.orgId(), this.query()),
  );
  protected readonly members = httpResource<Page<Member>>(() =>
    this.orgApi.membersRequest(this.org.orgId(), { limit: 100 }),
  );
  protected readonly memberNames = computed(
    () => new Map((this.members.value()?.items ?? []).map((m) => [m.user_id, m.full_name])),
  );
  protected readonly selected = signal<AuditEntry | null>(null);

  protected readonly hasFilters = computed(() =>
    ['action', 'resource', 'actor', 'outcome', 'since', 'until'].some((k) => !!this.q.get(k)),
  );

  protected actor(entry: AuditEntry): string {
    if (entry.actor_type === 'system') return 'System';
    if (!entry.actor_user_id) return 'Removed user';
    return this.memberNames().get(entry.actor_user_id) ?? 'Former member';
  }

  protected link(entry: AuditEntry): unknown[] | null {
    const route = RESOURCE_ROUTES[entry.resource_type];
    return route && entry.resource_id ? ['/o', this.org.orgId(), route, entry.resource_id] : null;
  }

  protected toggle(entry: AuditEntry): void {
    this.selected.set(this.selected()?.id === entry.id ? null : entry);
  }

  protected value(event: Event): string {
    return (event.target as HTMLInputElement | HTMLSelectElement).value;
  }
}

/** `datetime-local` gives local time without a zone; the API wants an ISO timestamp. */
function toIso(local: string): string | undefined {
  if (!local) return undefined;
  const date = new Date(local);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}
