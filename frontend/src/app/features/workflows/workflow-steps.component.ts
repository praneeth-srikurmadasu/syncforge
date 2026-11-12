import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { StepResponse } from '../../core/api/models';
import { IconComponent } from '../../shared/ui/icon.component';

/** A workflow's steps drawn as the ordered chain they run in. */
@Component({
  selector: 'sf-workflow-steps',
  imports: [RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <ol class="chain" [attr.aria-label]="'Steps for ' + trigger()">
      <li class="trigger">
        <span class="label">When</span>
        <code>{{ trigger() }}</code>
      </li>
      @for (s of steps(); track s.position) {
        <li class="arrow" aria-hidden="true"><sf-icon name="chevron-right" [size]="14" /></li>
        <li class="step">
          <span class="pos">{{ s.position }}</span>
          <span class="body">
            <code>{{ s.operation }}</code>
            <a [routerLink]="['/o', orgId(), 'connectors', s.connector_id]">{{
              s.connector_name
            }}</a>
          </span>
        </li>
      }
    </ol>
  `,
  styles: `
    .chain {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--sf-space-2);
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .trigger,
    .step {
      display: flex;
      align-items: center;
      gap: var(--sf-space-2);
      padding: 8px 12px;
      border: 1px solid var(--sf-border);
      border-radius: var(--sf-radius-md);
      background: var(--sf-bg-sunken);
      font-size: var(--sf-text-sm);
    }
    .trigger {
      border-color: color-mix(in srgb, var(--sf-accent) 40%, transparent);
      background: var(--sf-accent-soft);
    }
    .label {
      color: var(--sf-text-muted);
    }
    .arrow {
      color: var(--sf-text-faint);
      display: inline-flex;
    }
    .pos {
      display: grid;
      place-items: center;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      background: var(--sf-surface-hover);
      font-size: var(--sf-text-xs);
      font-weight: 600;
    }
    .body {
      display: flex;
      flex-direction: column;
      line-height: 1.3;
    }
    .body a {
      font-size: var(--sf-text-xs);
    }
  `,
})
export class WorkflowStepsComponent {
  readonly trigger = input.required<string>();
  readonly steps = input.required<StepResponse[]>();
  readonly orgId = input.required<string>();
}
