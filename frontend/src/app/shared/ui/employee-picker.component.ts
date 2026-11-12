import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  model,
  signal,
} from '@angular/core';
import { Subject, debounceTime, distinctUntilChanged, switchMap, catchError, of, map } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiError } from '../../core/api/api-error';
import { EmployeesApi } from '../../core/api/workforce.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { IconComponent } from './icon.component';

export interface EmployeeRefLike {
  id: string;
  full_name: string;
  employee_number: string;
}

/**
 * Chooses an employee by searching (name, email or number). As a manager picker it leaves
 * out terminated people and the employee being edited, which the API would refuse.
 */
@Component({
  selector: 'sf-employee-picker',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (value(); as current) {
      <div class="chosen">
        <span
          >{{ current.full_name }} <code class="sf-faint">{{ current.employee_number }}</code></span
        >
        <button type="button" class="sf-btn sf-btn--ghost sf-btn--sm" (click)="value.set(null)">
          <sf-icon name="x" [size]="13" /> Remove
        </button>
      </div>
    } @else {
      <input
        [id]="inputId()"
        class="sf-input"
        type="search"
        autocomplete="off"
        placeholder="Search by name, email or number"
        role="combobox"
        [attr.aria-expanded]="results().length > 0"
        [attr.aria-controls]="inputId() + '-list'"
        (input)="terms.next($any($event.target).value)"
      />
      @if (error()) {
        <span class="sf-field__error">{{ error() }}</span>
      }
      @if (results().length) {
        <ul class="results" role="listbox" [id]="inputId() + '-list'">
          @for (r of results(); track r.id) {
            <li role="option" [attr.aria-selected]="false">
              <button type="button" (click)="choose(r)">
                <span>{{ r.full_name }}</span>
                <code class="sf-faint">{{ r.employee_number }}</code>
              </button>
            </li>
          }
        </ul>
      } @else if (searched() && !error()) {
        <span class="sf-field__hint">{{ emptyText() }}</span>
      }
    }
  `,
  styles: `
    :host {
      display: block;
      position: relative;
    }
    .chosen {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--sf-space-2);
      height: 34px;
      padding: 0 4px 0 var(--sf-space-3);
      border: 1px solid var(--sf-border-strong);
      border-radius: var(--sf-radius-md);
      font-size: var(--sf-text-md);
    }
    .results {
      position: absolute;
      z-index: 5;
      left: 0;
      right: 0;
      margin: 4px 0 0;
      padding: 4px;
      list-style: none;
      border-radius: var(--sf-radius-md);
      background: var(--sf-surface-raised);
      box-shadow: var(--sf-shadow-overlay);
    }
    .results button {
      display: flex;
      justify-content: space-between;
      width: 100%;
      padding: 7px 8px;
      border: none;
      border-radius: var(--sf-radius-sm);
      background: none;
      color: var(--sf-text);
      font: inherit;
      font-size: var(--sf-text-sm);
      cursor: pointer;
    }
    .results button:hover,
    .results button:focus-visible {
      background: var(--sf-surface-hover);
    }
  `,
})
export class EmployeePickerComponent {
  private readonly api = inject(EmployeesApi);
  private readonly org = inject(OrgContextService);

  readonly value = model<EmployeeRefLike | null>(null);
  readonly excludeId = input<string | null>(null);
  readonly includeTerminated = input(false);
  readonly emptyText = input('No matching employee who can be a manager.');
  readonly inputId = input('manager');

  protected readonly terms = new Subject<string>();
  protected readonly results = signal<EmployeeRefLike[]>([]);
  protected readonly searched = signal(false);
  protected readonly error = signal<string | null>(null);

  constructor() {
    this.terms
      .pipe(
        map((t) => t.trim()),
        debounceTime(250),
        distinctUntilChanged(),
        switchMap((term) => {
          if (term.length < 2) return of(null);
          return this.api.list(this.org.orgId(), { search: term, limit: 10 }).pipe(
            map((page) => page.items),
            catchError((e: unknown) => {
              this.error.set(ApiError.from(e).message);
              return of([]);
            }),
          );
        }),
        takeUntilDestroyed(inject(DestroyRef)),
      )
      .subscribe((items) => {
        if (items === null) {
          this.results.set([]);
          this.searched.set(false);
          return;
        }
        if (items.length) this.error.set(null);
        this.searched.set(true);
        this.results.set(
          items
            .filter(
              (e) =>
                (this.includeTerminated() || e.employment_status !== 'terminated') &&
                e.id !== this.excludeId(),
            )
            .map((e) => ({ id: e.id, full_name: e.full_name, employee_number: e.employee_number })),
        );
      });
  }

  protected choose(ref: EmployeeRefLike): void {
    this.value.set(ref);
    this.results.set([]);
    this.searched.set(false);
  }
}
