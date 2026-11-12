import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { EMPTY, Observable, expand, reduce } from 'rxjs';
import { Employee, Page } from '../../core/api/models';
import { EmployeesApi } from '../../core/api/workforce.api';
import { TreeRow, groupByManager, visibleRows } from './reporting-tree';
import { OrgContextService } from '../../core/org/org-context.service';
import { StatusBadgeComponent } from '../../shared/ui/badge.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';

/** Read at most this many employees (10 pages of 100) to draw the chart. */
const MAX_EMPLOYEES = 1000;

interface Loaded {
  employees: Employee[];
  total: number;
}

/**
 * Reporting lines drawn from the employee list (manager references). The API has no tree
 * endpoint, so current, non-archived employees are read page by page (up to 1,000).
 * Terminated people are left out: their reports were moved to the next manager up.
 */
@Component({
  selector: 'sf-reporting',
  imports: [
    RouterLink,
    PageHeaderComponent,
    StatusBadgeComponent,
    IconComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="sf-page">
      <sf-page-header
        title="Reporting lines"
        description="Who reports to whom, from each employee's manager. Select a row's arrow to expand or collapse a team."
      >
        @if (rows()) {
          <button type="button" class="sf-btn" (click)="expandAll()">Expand all</button>
          <button type="button" class="sf-btn" (click)="collapsed.set(allManagers())">
            Collapse all
          </button>
        }
      </sf-page-header>

      @if (data.value(); as d) {
        @if (d.total > d.employees.length) {
          <div class="sf-alert sf-alert--warning" role="status">
            Showing the first {{ d.employees.length }} of {{ d.total }} employees. People whose
            manager is not among them appear at the top level.
          </div>
        }
      }

      <div class="sf-card">
        @if (data.error(); as err) {
          <sf-error-state [error]="err" (retry)="data.reload()" />
        } @else if (rows(); as list) {
          @if (list.length === 0) {
            <sf-empty-state icon="network" title="No current employees" />
          } @else {
            <ul class="tree" aria-label="Reporting lines">
              @for (row of list; track row.employee.id) {
                <li [style.padding-left.px]="16 + row.depth * 24">
                  @if (row.reports) {
                    <button
                      type="button"
                      class="toggle"
                      [attr.aria-expanded]="!collapsed().has(row.employee.id)"
                      [attr.aria-label]="
                        (collapsed().has(row.employee.id) ? 'Expand ' : 'Collapse ') +
                        row.employee.full_name
                      "
                      (click)="toggle(row.employee.id)"
                    >
                      <sf-icon
                        [name]="collapsed().has(row.employee.id) ? 'chevron-right' : 'chevron-down'"
                        [size]="14"
                      />
                    </button>
                  } @else {
                    <span class="toggle-pad"></span>
                  }
                  <a
                    class="name"
                    [routerLink]="['/o', org.orgId(), 'employees', row.employee.id]"
                    >{{ row.employee.full_name }}</a
                  >
                  <span class="sf-muted role">{{ row.employee.designation ?? '' }}</span>
                  <span class="sf-faint dept">{{ row.employee.department?.name ?? '' }}</span>
                  @if (row.reports) {
                    <span class="sf-faint count"
                      >{{ row.reports }} {{ row.reports === 1 ? 'report' : 'reports' }}</span
                    >
                  }
                  @if (row.employee.employment_status === 'on_leave') {
                    <sf-status value="on_leave" />
                  }
                </li>
              }
            </ul>
          }
        } @else {
          <sf-skeleton [rows]="10" />
        }
      </div>
    </div>
  `,
  styles: `
    .tree {
      margin: 0;
      padding: var(--sf-space-2) 0;
      list-style: none;
    }
    li {
      display: flex;
      align-items: center;
      gap: var(--sf-space-3);
      min-height: 38px;
      padding-right: var(--sf-space-4);
      font-size: var(--sf-text-sm);
      border-bottom: 1px solid var(--sf-border);
    }
    li:last-child {
      border-bottom: none;
    }
    .toggle {
      display: grid;
      place-items: center;
      width: 22px;
      height: 22px;
      padding: 0;
      border: none;
      border-radius: var(--sf-radius-sm);
      background: none;
      color: var(--sf-text-muted);
      cursor: pointer;
    }
    .toggle:hover {
      background: var(--sf-surface-hover);
    }
    .toggle-pad {
      width: 22px;
    }
    .name {
      color: var(--sf-text);
      font-weight: 500;
    }
    .role {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .dept {
      margin-left: auto;
    }
    .count {
      width: 80px;
      text-align: right;
    }
    @media (max-width: 720px) {
      .dept,
      .role {
        display: none;
      }
    }
  `,
})
export class ReportingComponent {
  protected readonly org = inject(OrgContextService);
  private readonly api = inject(EmployeesApi);

  protected readonly collapsed = signal<Set<string>>(new Set());

  protected readonly data = rxResource({
    params: () => this.org.orgId(),
    stream: ({ params }) => this.loadAll(params),
  });

  private readonly children = computed(() => {
    const d = this.data.value();
    return d ? groupByManager(d.employees) : null;
  });

  protected readonly allManagers = computed(() => {
    const map = this.children();
    return new Set([...(map?.keys() ?? [])].filter((k): k is string => k !== null));
  });

  protected readonly rows = computed<TreeRow[] | null>(() => {
    const map = this.children();
    return map ? visibleRows(map, this.collapsed()) : null;
  });

  protected toggle(id: string): void {
    this.collapsed.update((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  protected expandAll(): void {
    this.collapsed.set(new Set());
  }

  private loadAll(orgId: string): Observable<Loaded> {
    const pageOf = (offset: number) =>
      this.api.list(orgId, { limit: 100, offset, sort: 'last_name' });
    return pageOf(0).pipe(
      expand((page: Page<Employee>) => {
        const next = page.offset + page.limit;
        return next < page.total && next < MAX_EMPLOYEES ? pageOf(next) : EMPTY;
      }),
      reduce<Page<Employee>, Loaded>(
        (acc, page) => ({ employees: [...acc.employees, ...page.items], total: page.total }),
        { employees: [], total: 0 },
      ),
    );
  }
}
