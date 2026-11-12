import { httpResource } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ApiError } from '../../core/api/api-error';
import { ConnectorsApi, WorkflowsApi } from '../../core/api/integrations.api';
import {
  Connector,
  EVENT_TYPES,
  EventType,
  Page,
  StepInput,
  StepOperation,
  Workflow,
} from '../../core/api/models';
import { OrgContextService } from '../../core/org/org-context.service';
import { ToastService } from '../../core/toast/toast.service';
import { BadgeComponent } from '../../shared/ui/badge.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { ErrorStateComponent, SkeletonComponent } from '../../shared/ui/states.component';

const OPERATIONS: StepOperation[] = ['create_user', 'update_user', 'deactivate_user'];
const MAX_STEPS = 20; // the API's limit (WorkflowCreate.steps max_length)

/** Which operation usually fits each trigger - offered as a hint, never enforced. */
const SUGGESTED: Record<EventType, StepOperation> = {
  'employee.created': 'create_user',
  'employee.updated': 'update_user',
  'employee.department_changed': 'update_user',
  'employee.manager_changed': 'update_user',
  'employee.terminated': 'deactivate_user',
};

interface DraftStep {
  key: number;
  connector_id: string;
  operation: StepOperation;
}

/**
 * Create or edit a workflow: a trigger and an ordered list of steps (connector + operation),
 * exactly what the API stores. Saving changed steps or trigger makes a new version;
 * executions keep the version they ran.
 */
@Component({
  selector: 'sf-workflow-builder',
  imports: [
    FormsModule,
    RouterLink,
    PageHeaderComponent,
    IconComponent,
    BadgeComponent,
    ErrorStateComponent,
    SkeletonComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './workflow-builder.component.html',
  styleUrl: './workflow-builder.component.scss',
})
export class WorkflowBuilderComponent {
  /** Route parameter; absent on /workflows/new. */
  readonly id = input<string>();

  protected readonly org = inject(OrgContextService);
  private readonly api = inject(WorkflowsApi);
  private readonly connectorsApi = inject(ConnectorsApi);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);

  protected readonly triggers = EVENT_TYPES;
  protected readonly operations = OPERATIONS;
  protected readonly maxSteps = MAX_STEPS;

  protected readonly existing = httpResource<Workflow>(() => {
    const id = this.id();
    return id ? this.api.getRequest(this.org.orgId(), id) : undefined;
  });
  protected readonly connectors = httpResource<Page<Connector>>(() =>
    this.connectorsApi.listRequest(this.org.orgId()),
  );

  protected name = '';
  protected description = '';
  protected readonly trigger = signal<EventType>('employee.created');
  protected readonly steps = signal<DraftStep[]>([]);
  private nextKey = 1;
  private loaded = false;

  protected readonly busy = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly submitted = signal(false);

  protected readonly suggested = computed(() => SUGGESTED[this.trigger()]);
  protected readonly connectorById = computed(
    () => new Map((this.connectors.value()?.items ?? []).map((c) => [c.id, c])),
  );
  /** Same connector + operation twice is refused by the API (duplicate_step). */
  protected readonly duplicateKeys = computed(() => {
    const seen = new Map<string, number>();
    for (const s of this.steps()) {
      const k = `${s.connector_id}|${s.operation}`;
      seen.set(k, (seen.get(k) ?? 0) + 1);
    }
    return new Set(
      this.steps()
        .filter((s) => (seen.get(`${s.connector_id}|${s.operation}`) ?? 0) > 1)
        .map((s) => s.key),
    );
  });
  protected readonly problems = computed(() => {
    const list: string[] = [];
    if (!this.steps().length) list.push('Add at least one step.');
    if (this.steps().some((s) => !s.connector_id)) list.push('Choose a connector for every step.');
    if (this.duplicateKeys().size) list.push('Each connector and operation can appear only once.');
    return list;
  });

  constructor() {
    // Fill the form once the workflow being edited has loaded.
    effect(() => {
      const w = this.existing.value();
      if (!w || this.loaded) return;
      this.loaded = true;
      this.name = w.name;
      this.description = w.description ?? '';
      this.trigger.set(w.trigger_event_type as EventType);
      this.steps.set(
        w.steps.map((s) => ({
          key: this.nextKey++,
          connector_id: s.connector_id,
          operation: s.operation,
        })),
      );
    });
  }

  protected addStep(): void {
    this.steps.update((list) => [
      ...list,
      { key: this.nextKey++, connector_id: '', operation: this.suggested() },
    ]);
  }

  protected updateStep(key: number, patch: Partial<DraftStep>): void {
    this.steps.update((list) => list.map((s) => (s.key === key ? { ...s, ...patch } : s)));
  }

  protected move(index: number, delta: -1 | 1): void {
    this.steps.update((list) => {
      const next = [...list];
      const target = index + delta;
      if (target < 0 || target >= next.length) return list;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  protected remove(key: number): void {
    this.steps.update((list) => list.filter((s) => s.key !== key));
  }

  protected save(): void {
    this.submitted.set(true);
    if (!this.name.trim() || this.problems().length) return;
    this.busy.set(true);
    this.error.set(null);
    const steps: StepInput[] = this.steps().map((s) => ({
      connector_id: s.connector_id,
      operation: s.operation,
    }));
    const body = {
      name: this.name.trim(),
      description: this.description.trim() || null,
      trigger_event_type: this.trigger(),
      steps,
    };
    const id = this.id();
    const request = id
      ? this.api.update(this.org.orgId(), id, body)
      : this.api.create(this.org.orgId(), body);
    request.subscribe({
      next: (w) => {
        this.toast.success(
          id
            ? `Saved ${w.name} (version ${w.version})`
            : `Created ${w.name}. It is inactive until you activate it.`,
        );
        void this.router.navigate(['/o', this.org.orgId(), 'workflows', w.id]);
      },
      error: (e: unknown) => {
        this.busy.set(false);
        this.error.set(ApiError.from(e));
      },
    });
  }
}
