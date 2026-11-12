import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { ConnectorsApi } from '../../core/api/integrations.api';
import { ConnectionTest, Connector, ConnectorType, ReconcileResult } from '../../core/api/models';
import { OrgContextService } from '../../core/org/org-context.service';
import { ToastService } from '../../core/toast/toast.service';
import { formatDuration, humanize } from '../../core/util/format';
import { BadgeComponent, StatusBadgeComponent } from '../../shared/ui/badge.component';
import { CopyIdComponent } from '../../shared/ui/copy-id.component';
import { DialogService } from '../../shared/ui/dialog';
import { IconComponent } from '../../shared/ui/icon.component';
import { JsonViewComponent } from '../../shared/ui/json-view.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { ErrorStateComponent, SkeletonComponent } from '../../shared/ui/states.component';
import { TabItem, TabsComponent } from '../../shared/ui/tabs.component';
import { TimeComponent } from '../../shared/ui/time.component';
import { ConnectorActivityComponent } from './connector-activity.component';
import { ConnectorFormData, ConnectorFormDialogComponent } from './connector-form.dialog';
import { ConnectorOperationComponent } from './connector-operation.component';

@Component({
  selector: 'sf-connector-detail',
  imports: [
    PageHeaderComponent,
    BadgeComponent,
    StatusBadgeComponent,
    CopyIdComponent,
    IconComponent,
    JsonViewComponent,
    TabsComponent,
    TimeComponent,
    ErrorStateComponent,
    SkeletonComponent,
    ConnectorActivityComponent,
    ConnectorOperationComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './connector-detail.component.html',
  styleUrl: './connector-detail.component.scss',
})
export class ConnectorDetailComponent {
  readonly id = input.required<string>();

  protected readonly org = inject(OrgContextService);
  private readonly api = inject(ConnectorsApi);
  private readonly dialogs = inject(DialogService);
  private readonly toast = inject(ToastService);

  protected readonly humanize = humanize;
  protected readonly formatDuration = formatDuration;
  protected readonly tab = signal('overview');

  protected readonly connector = httpResource<Connector>(() =>
    this.api.getRequest(this.org.orgId(), this.id()),
  );
  protected readonly types = httpResource<ConnectorType[]>(() => this.api.typesRequest());
  protected readonly type = computed(() =>
    this.types.value()?.find((t) => t.connector_type === this.connector.value()?.connector_type),
  );

  protected readonly testing = signal(false);
  protected readonly testResult = signal<ConnectionTest | null>(null);
  protected readonly reconciling = signal(false);
  protected readonly reconcileResult = signal<ReconcileResult | null>(null);

  protected readonly configEntries = computed(() =>
    Object.entries(this.connector.value()?.config ?? {}).map(([key, value]) => ({
      key,
      value: value === null || value === undefined ? '-' : String(value),
    })),
  );

  protected readonly tabs = computed<TabItem[]>(() => {
    const tabs: TabItem[] = [
      { id: 'overview', label: 'Overview' },
      { id: 'accounts', label: 'Linked accounts' },
    ];
    if (this.org.can('connectors:manage'))
      tabs.push({ id: 'operation', label: 'Run an operation' });
    tabs.push(
      { id: 'dead-letters', label: 'Dead letters' },
      { id: 'conflicts', label: 'Conflicts' },
    );
    if (this.org.can('audit:read')) tabs.push({ id: 'history', label: 'History' });
    return tabs;
  });

  /** The normalized connector error inside a failed test (category, message, HTTP status). */
  protected testError(
    t: ConnectionTest,
  ): { category: string; message: string; status_code: number | null } | null {
    const e = t.error as Record<string, unknown> | null | undefined;
    if (!e) return null;
    return {
      category: String(e['category'] ?? 'error'),
      message: String(e['message'] ?? ''),
      status_code: typeof e['status_code'] === 'number' ? e['status_code'] : null,
    };
  }

  protected test(c: Connector): void {
    this.testing.set(true);
    this.api.test(this.org.orgId(), c.id).subscribe({
      next: (result) => {
        this.testing.set(false);
        this.testResult.set(result);
        this.connector.reload(); // status and last_tested_at changed
      },
      error: (e: unknown) => {
        this.testing.set(false);
        this.toast.error(e, 'Connection test could not run');
      },
    });
  }

  protected edit(c: Connector, mode: 'settings' | 'credentials'): void {
    const type = this.type();
    if (!type) return;
    const ref = this.dialogs.open<Connector, ConnectorFormData, ConnectorFormDialogComponent>(
      ConnectorFormDialogComponent,
      { mode, type, connector: c },
      true,
    );
    ref.closed.subscribe((saved) => {
      if (!saved) return;
      this.connector.set(saved);
      this.testResult.set(null);
      this.toast.success(
        mode === 'settings'
          ? 'Settings saved'
          : 'Credentials replaced. Test the connection to confirm them.',
      );
    });
  }

  protected async disconnect(c: Connector): Promise<void> {
    const ok = await this.dialogs.confirm({
      title: `Disconnect ${c.name}?`,
      message:
        'The stored credentials are deleted and workflow steps for this connector fail until new credentials are saved. Accounts already created in the application are not changed.',
      confirmLabel: 'Disconnect',
      tone: 'danger',
      typeToConfirm: c.name,
    });
    if (!ok) return;
    this.api.disconnect(this.org.orgId(), c.id).subscribe({
      next: (updated) => {
        this.connector.set(updated);
        this.testResult.set(null);
        this.toast.success(`${c.name} disconnected; credentials deleted`);
      },
      error: (e: unknown) => this.toast.error(e, 'Disconnect failed'),
    });
  }

  protected reconcile(c: Connector): void {
    this.reconciling.set(true);
    this.api.reconcile(this.org.orgId(), c.id).subscribe({
      next: (result) => {
        this.reconciling.set(false);
        this.reconcileResult.set(result);
      },
      error: (e: unknown) => {
        this.reconciling.set(false);
        this.toast.error(e, 'Reconciliation failed');
      },
    });
  }
}
