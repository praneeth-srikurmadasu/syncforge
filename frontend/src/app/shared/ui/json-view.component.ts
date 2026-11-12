import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/** Structured details (audit entries, connector errors) shown as formatted JSON text. */
@Component({
  selector: 'sf-json',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<pre>{{ text() }}</pre>`,
  styles: `
    pre {
      margin: 0;
      padding: var(--sf-space-3);
      max-height: 320px;
      overflow: auto;
      border-radius: var(--sf-radius-md);
      background: var(--sf-bg-sunken);
      font-family: var(--sf-font-mono);
      font-size: var(--sf-text-xs);
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
    }
  `,
})
export class JsonViewComponent {
  readonly value = input<unknown>();
  protected readonly text = computed(() => JSON.stringify(this.value() ?? {}, null, 2));
}
