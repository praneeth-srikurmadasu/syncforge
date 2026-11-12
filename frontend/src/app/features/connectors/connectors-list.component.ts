import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { ConnectorsApi } from '../../core/api/integrations.api';
import { Connector, ConnectorType, Page } from '../../core/api/models';
import { OrgContextService } from '../../core/org/org-context.service';
import { ToastService } from '../../core/toast/toast.service';
import { BadgeComponent, StatusBadgeComponent } from '../../shared/ui/badge.component';
import { DialogService } from '../../shared/ui/dialog';
import { IconComponent } from '../../shared/ui/icon.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';
import { ConnectorFormData, ConnectorFormDialogComponent } from './connector-form.dialog';

@Component({
  selector: 'sf-connectors-list',
  imports: [
    RouterLink,
    PageHeaderComponent,
    BadgeComponent,
    StatusBadgeComponent,
    IconComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './connectors-list.component.html',
  styleUrl: './connectors-list.component.scss',
})
export class ConnectorsListComponent {
  protected readonly org = inject(OrgContextService);
  private readonly api = inject(ConnectorsApi);
  private readonly dialogs = inject(DialogService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);

  protected readonly types = httpResource<ConnectorType[]>(() => this.api.typesRequest());
  protected readonly connectors = httpResource<Page<Connector>>(() =>
    this.api.listRequest(this.org.orgId()),
  );

  /** How many connectors of each type the organization already has. */
  protected readonly countByType = computed(() => {
    const counts = new Map<string, number>();
    for (const c of this.connectors.value()?.items ?? []) {
      counts.set(c.connector_type, (counts.get(c.connector_type) ?? 0) + 1);
    }
    return counts;
  });

  protected readonly typeNames = computed(
    () => new Map((this.types.value() ?? []).map((t) => [t.connector_type, t.display_name])),
  );

  protected connect(type: ConnectorType): void {
    const ref = this.dialogs.open<Connector, ConnectorFormData, ConnectorFormDialogComponent>(
      ConnectorFormDialogComponent,
      { mode: 'create', type },
      true,
    );
    ref.closed.subscribe((created) => {
      if (!created) return;
      this.toast.success(
        `Created ${created.name}. Test the connection to confirm the credentials.`,
      );
      void this.router.navigate(['/o', this.org.orgId(), 'connectors', created.id]);
    });
  }

  protected open(c: Connector): void {
    void this.router.navigate(['/o', this.org.orgId(), 'connectors', c.id]);
  }
}
