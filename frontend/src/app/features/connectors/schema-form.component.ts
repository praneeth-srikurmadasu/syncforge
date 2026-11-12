import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { controlError } from '../../shared/forms';
import { PasswordFieldComponent } from '../../shared/ui/password-field.component';
import { SchemaField } from './schema-fields';

/** Renders the controls for a list of schema fields inside an existing FormGroup. */
@Component({
  selector: 'sf-schema-form',
  imports: [ReactiveFormsModule, PasswordFieldComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="sf-form-grid" [formGroup]="group()">
      @for (f of fields(); track f.name) {
        <div class="sf-field" [class.sf-span-2]="f.kind === 'url' || f.kind === 'secret'">
          @if (f.kind === 'boolean') {
            <label class="sf-checkbox">
              <input type="checkbox" [formControlName]="f.name" />
              {{ f.label }}
            </label>
          } @else {
            <label [for]="idPrefix() + f.name">
              {{ f.label }}
              @if (!f.required) {
                <span class="sf-faint">(optional)</span>
              }
            </label>
            @switch (f.kind) {
              @case ('secret') {
                <sf-password-field>
                  <input
                    [id]="idPrefix() + f.name"
                    class="sf-input sf-mono"
                    type="password"
                    autocomplete="new-password"
                    [formControlName]="f.name"
                  />
                </sf-password-field>
              }
              @case ('select') {
                <select [id]="idPrefix() + f.name" class="sf-select" [formControlName]="f.name">
                  @for (o of f.options; track o) {
                    <option [value]="o">{{ o }}</option>
                  }
                </select>
              }
              @case ('integer') {
                <input
                  [id]="idPrefix() + f.name"
                  class="sf-input"
                  type="number"
                  [attr.min]="f.minimum ?? null"
                  [attr.max]="f.maximum ?? null"
                  [formControlName]="f.name"
                />
              }
              @default {
                <input
                  [id]="idPrefix() + f.name"
                  class="sf-input"
                  [class.sf-mono]="f.kind === 'url'"
                  [type]="f.kind === 'url' ? 'url' : 'text'"
                  autocomplete="off"
                  [formControlName]="f.name"
                />
              }
            }
          }
          @if (controlError(group().get(f.name), f.label); as m) {
            <span class="sf-field__error">{{ m }}</span>
          } @else if (f.description) {
            <span class="sf-field__hint">{{ f.description }}</span>
          }
        </div>
      }
    </div>
  `,
})
export class SchemaFormComponent {
  readonly fields = input.required<SchemaField[]>();
  readonly group = input.required<FormGroup>();
  readonly idPrefix = input('sf-');
  protected readonly controlError = controlError;
}
