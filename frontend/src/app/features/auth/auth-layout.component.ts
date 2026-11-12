import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { ThemeService } from '../../core/theme/theme.service';
import { IconComponent } from '../../shared/ui/icon.component';
import { BrandMarkComponent } from '../../layout/brand-mark.component';

/** Frame for the signed-out screens: the form on one side, what SyncForge does on the other. */
@Component({
  selector: 'sf-auth-layout',
  imports: [RouterOutlet, BrandMarkComponent, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="wrap">
      <section class="form-side">
        <header>
          <sf-brand-mark [size]="28" />
          <span class="name">SyncForge</span>
          <span class="sf-spacer"></span>
          <button
            type="button"
            class="sf-btn sf-btn--ghost sf-btn--icon"
            [attr.aria-label]="
              theme.theme() === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'
            "
            (click)="theme.toggle()"
          >
            <sf-icon [name]="theme.theme() === 'dark' ? 'sun' : 'moon'" />
          </button>
        </header>
        <div class="form-area"><router-outlet /></div>
      </section>
      <aside class="story" aria-label="About SyncForge">
        <p class="statement">
          One employee record.<br />
          Every system kept in step.
        </p>
        <svg class="flow" viewBox="0 0 360 220" role="img" aria-labelledby="flow-title">
          <title id="flow-title">
            An employee change in SyncForge flows through events and workflows to Slack, Google
            Workspace and payroll.
          </title>
          <g class="lines">
            <path d="M92 110 H150" />
            <path d="M210 110 C240 110 240 46 266 46" />
            <path d="M210 110 H266" />
            <path d="M210 110 C240 110 240 174 266 174" />
          </g>
          <g class="node source">
            <rect x="8" y="88" width="84" height="44" rx="8" />
            <text x="50" y="114">Employee</text>
          </g>
          <g class="node hub">
            <rect x="150" y="84" width="60" height="52" rx="10" />
            <circle cx="180" cy="110" r="5" />
          </g>
          <g class="node">
            <rect x="266" y="26" width="86" height="40" rx="8" />
            <text x="309" y="50">Slack</text>
          </g>
          <g class="node">
            <rect x="266" y="90" width="86" height="40" rx="8" />
            <text x="309" y="114">Google</text>
          </g>
          <g class="node">
            <rect x="266" y="154" width="86" height="40" rx="8" />
            <text x="309" y="178">Payroll</text>
          </g>
        </svg>
        <ul class="points">
          <li>Lifecycle events are written with the change and processed by background workers.</li>
          <li>
            Failed calls are retried with backoff, then held in a dead-letter queue for replay.
          </li>
          <li>
            Disagreements between systems become conflicts, decided by your source-of-truth rules.
          </li>
        </ul>
        <p class="note">
          In this local environment the Slack, Google Workspace and payroll systems are simulated
          services that run alongside SyncForge.
        </p>
      </aside>
    </div>
  `,
  styleUrl: './auth-layout.component.scss',
})
export class AuthLayoutComponent {
  protected readonly theme = inject(ThemeService);
}
