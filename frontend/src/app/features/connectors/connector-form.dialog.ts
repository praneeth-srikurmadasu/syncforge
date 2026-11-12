import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ApiError } from '../../core/api/api-error';
import { ConnectorsApi } from '../../core/api/integrations.api';
import { Connector, ConnectorType } from '../../core/api/models';
import { OrgContextService } from '../../core/org/org-context.service';
import { applyServerErrors, controlError } from '../../shared/forms';
import { BadgeComponent } from '../../shared/ui/badge.component';
import { DialogFrameComponent } from '../../shared/ui/dialog';
import { SchemaFormComponent } from './schema-form.component';
import { buildGroup, fieldValues, schemaFields } from './schema-fields';

export type ConnectorFormData =
  | { mode: 'create'; type: ConnectorType }
  | { mode: 'settings'; type: ConnectorType; connector: Connector }
  | { mode: 'credentials'; type: ConnectorType; connector: Connector };

/**
 * Create a connector, change its name and settings, or replace its credentials. Stored
 * credentials are never sent back by the API, so they can only be replaced, not edited.
 */
@Component({
  selector: 'sf-connector-form-dialog',
  imports: [ReactiveFormsModule, DialogFrameComponent, SchemaFormComponent, BadgeComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <sf-dialog [title]="title()" [description]="data.type.description">
      @if (data.type.simulated) {
        <div class="sf-alert sf-alert--info note">
          <span>
            <sf-badge tone="info">Simulated</sf-badge>
            This connector talks to the local mock {{ data.type.display_name }} service, not the
            real product. Use the test credentials listed in <code>mock-services/README.md</code>;
            the mock refuses other values, as the real service would.
          </span>
        </div>
      }
      @if (error(); as err) {
        <div class="sf-alert sf-alert--danger note" role="alert">
          <span>
            {{ err.message }}
            @for (issue of extraIssues(); track issue) {
              <br />{{ issue }}
            }
          </span>
        </div>
      }
      <form
        id="connector-form"
        class="sections"
        (submit)="$event.preventDefault(); submit()"
        novalidate
      >
        @if (data.mode !== 'credentials') {
          <section>
            <div class="sf-field">
              <label for="cf-name">Name</label>
              <input id="cf-name" class="sf-input" [formControl]="name" autocomplete="off" />
              @if (controlError(name, 'Name'); as m) {
                <span class="sf-field__error">{{ m }}</span>
              } @else {
                <span class="sf-field__hint"
                  >Shown in workflows; must be unique in the organization.</span
                >
              }
            </div>
          </section>
          @if (configFields.length) {
            <section>
              <h3>Settings</h3>
              <sf-schema-form [fields]="configFields" [group]="config" idPrefix="cfg-" />
            </section>
          }
        }
        @if (data.mode !== 'settings') {
          <section>
            <h3>
              Credentials <span class="sf-faint">({{ data.type.auth_type }})</span>
            </h3>
            <p class="sf-muted small">
              Encrypted before they are stored. They are never shown again; the connector page shows
              only the last four characters.
            </p>
            <sf-schema-form [fields]="credentialFields" [group]="credentials" idPrefix="cred-" />
          </section>
        }
      </form>
      <ng-container footer>
        <button type="button" class="sf-btn" (click)="ref.close()">Cancel</button>
        <button
          type="submit"
          form="connector-form"
          class="sf-btn sf-btn--primary"
          [disabled]="busy()"
        >
          {{ busy() ? 'Saving…' : submitLabel() }}
        </button>
      </ng-container>
    </sf-dialog>
  `,
  styles: `
    .note {
      margin-bottom: var(--sf-space-4);
    }
    .sections {
      display: flex;
      flex-direction: column;
      gap: var(--sf-space-5);
    }
    section {
      display: flex;
      flex-direction: column;
      gap: var(--sf-space-3);
    }
    .small {
      font-size: var(--sf-text-sm);
    }
  `,
})
export class ConnectorFormDialogComponent {
  protected readonly data = inject<ConnectorFormData>(DIALOG_DATA);
  protected readonly ref = inject<DialogRef<Connector>>(DialogRef);
  private readonly api = inject(ConnectorsApi);
  private readonly org = inject(OrgContextService);
  protected readonly controlError = controlError;

  private readonly existing = this.data.mode === 'create' ? null : this.data.connector;
  protected readonly configFields = schemaFields(this.data.type.config_schema);
  protected readonly credentialFields = schemaFields(this.data.type.credentials_schema);

  protected readonly name = new FormControl(this.existing?.name ?? this.data.type.connector_type, {
    nonNullable: true,
    validators: [Validators.required, Validators.maxLength(100)],
  });
  protected readonly config = buildGroup(this.configFields, this.existing?.config ?? {});
  protected readonly credentials = buildGroup(this.credentialFields);

  protected readonly busy = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly extraIssues = signal<string[]>([]);

  protected readonly title = computed(() => {
    if (this.data.mode === 'create') return `Connect ${this.data.type.display_name}`;
    if (this.data.mode === 'settings') return `Edit ${this.existing!.name}`;
    return this.existing!.status === 'disconnected'
      ? `Reconnect ${this.existing!.name}`
      : `Replace credentials for ${this.existing!.name}`;
  });
  protected readonly submitLabel = computed(() =>
    this.data.mode === 'create'
      ? 'Create connector'
      : this.data.mode === 'settings'
        ? 'Save settings'
        : 'Save credentials',
  );

  protected submit(): void {
    const groups: FormGroup[] = [];
    if (this.data.mode !== 'credentials') groups.push(this.config);
    if (this.data.mode !== 'settings') groups.push(this.credentials);
    const nameInvalid = this.data.mode !== 'credentials' && this.name.invalid;
    if (nameInvalid || groups.some((g) => g.invalid)) {
      this.name.markAsTouched();
      groups.forEach((g) => g.markAllAsTouched());
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    const config = fieldValues(this.configFields, this.config.getRawValue());
    const credentials = fieldValues(this.credentialFields, this.credentials.getRawValue());
    const orgId = this.org.orgId();

    const request =
      this.data.mode === 'create'
        ? this.api.create(orgId, {
            connector_type: this.data.type.connector_type,
            name: this.name.value.trim(),
            config,
            credentials,
          })
        : this.data.mode === 'settings'
          ? this.api.update(orgId, this.existing!.id, { name: this.name.value.trim(), config })
          : this.api.update(orgId, this.existing!.id, { credentials });

    request.subscribe({
      next: (connector) => this.ref.close(connector),
      error: (e: unknown) => {
        const apiError = ApiError.from(e);
        this.busy.set(false);
        this.error.set(apiError);
        // Field paths look like "config.rate_limit_per_minute" or "credentials.token".
        const unmatched = applyServerErrors(
          new FormGroup({ name: this.name, config: this.config, credentials: this.credentials }),
          apiError,
        );
        this.extraIssues.set(unmatched);
      },
    });
  }
}
