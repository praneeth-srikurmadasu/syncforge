import { Dialog, DialogConfig, DialogRef, DIALOG_DATA } from '@angular/cdk/dialog';
import { createGlobalPositionStrategy } from '@angular/cdk/overlay';
import { ComponentType } from '@angular/cdk/portal';
import {
  ChangeDetectionStrategy,
  Component,
  Injectable,
  Injector,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { IconComponent } from './icon.component';

/** Frame shared by every dialog and drawer: title, close button, body, footer. */
@Component({
  selector: 'sf-dialog',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header>
      <div>
        <h2 [id]="titleId">{{ title() }}</h2>
        @if (description()) {
          <p class="sf-muted">{{ description() }}</p>
        }
      </div>
      <button
        type="button"
        class="sf-btn sf-btn--ghost sf-btn--icon"
        aria-label="Close"
        (click)="close()"
      >
        <sf-icon name="x" />
      </button>
    </header>
    <div class="body"><ng-content /></div>
    <footer><ng-content select="[footer]" /></footer>
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      min-height: 100%;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: var(--sf-space-3);
      padding: var(--sf-space-4) var(--sf-space-5) 0;
    }
    header p {
      margin-top: 4px;
      font-size: var(--sf-text-sm);
    }
    .body {
      flex: 1;
      padding: var(--sf-space-4) var(--sf-space-5);
    }
    footer:not(:empty) {
      display: flex;
      justify-content: flex-end;
      gap: var(--sf-space-2);
      padding: var(--sf-space-3) var(--sf-space-5);
      border-top: 1px solid var(--sf-border);
    }
  `,
})
export class DialogFrameComponent {
  private readonly ref = inject(DialogRef, { optional: true });
  readonly title = input.required<string>();
  readonly description = input<string>();
  protected readonly titleId = `sf-dialog-${Math.random().toString(36).slice(2, 9)}`;

  close(): void {
    this.ref?.close();
  }
}

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel: string;
  tone?: 'primary' | 'danger';
  /** For irreversible actions: the user must type this text to enable the button. */
  typeToConfirm?: string;
}

@Component({
  selector: 'sf-confirm-dialog',
  imports: [DialogFrameComponent, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <sf-dialog [title]="data.title">
      <p>{{ data.message }}</p>
      @if (data.typeToConfirm) {
        <div class="sf-field confirm">
          <label for="sf-confirm-input"
            >Type <code>{{ data.typeToConfirm }}</code> to confirm</label
          >
          <input
            id="sf-confirm-input"
            class="sf-input"
            autocomplete="off"
            [ngModel]="typed()"
            (ngModelChange)="typed.set($event)"
          />
        </div>
      }
      <ng-container footer>
        <button type="button" class="sf-btn" (click)="ref.close(false)">Cancel</button>
        <button
          type="button"
          class="sf-btn"
          [class.sf-btn--danger]="data.tone === 'danger'"
          [class.sf-btn--primary]="data.tone !== 'danger'"
          [disabled]="data.typeToConfirm && typed() !== data.typeToConfirm"
          (click)="ref.close(true)"
        >
          {{ data.confirmLabel }}
        </button>
      </ng-container>
    </sf-dialog>
  `,
  styles: `
    p {
      font-size: var(--sf-text-md);
      color: var(--sf-text-muted);
    }
    .confirm {
      margin-top: var(--sf-space-4);
    }
  `,
})
export class ConfirmDialogComponent {
  protected readonly data = inject<ConfirmOptions>(DIALOG_DATA);
  protected readonly ref = inject<DialogRef<boolean>>(DialogRef);
  protected readonly typed = signal('');
}

/** Opens dialogs and drawers with consistent configuration. */
@Injectable({ providedIn: 'root' })
export class DialogService {
  private readonly dialog = inject(Dialog);
  private readonly injector = inject(Injector);

  open<R, D, C>(component: ComponentType<C>, data?: D, wide = false): DialogRef<R, C> {
    return this.dialog.open<R, D, C>(component, {
      data,
      panelClass: wide ? ['sf-dialog-panel', 'sf-dialog-panel--wide'] : 'sf-dialog-panel',
      backdropClass: 'cdk-overlay-dark-backdrop',
      autoFocus: 'first-tabbable',
      restoreFocus: true,
    } as DialogConfig<D, DialogRef<R, C>>);
  }

  drawer<R, D, C>(component: ComponentType<C>, data?: D): DialogRef<R, C> {
    return this.dialog.open<R, D, C>(component, {
      data,
      panelClass: 'sf-drawer-panel',
      backdropClass: 'cdk-overlay-dark-backdrop',
      positionStrategy: createGlobalPositionStrategy(this.injector).top('0').right('0'),
      autoFocus: 'dialog',
      restoreFocus: true,
    } as DialogConfig<D, DialogRef<R, C>>);
  }

  async confirm(options: ConfirmOptions): Promise<boolean> {
    const ref = this.open<boolean, ConfirmOptions, ConfirmDialogComponent>(
      ConfirmDialogComponent,
      options,
    );
    return (await firstValueFrom(ref.closed)) === true;
  }
}
