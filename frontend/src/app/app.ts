import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { ThemeService } from './core/theme/theme.service';
import { ToastOutletComponent } from './shared/ui/toast-outlet.component';

@Component({
  selector: 'sf-root',
  imports: [RouterOutlet, ToastOutletComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<router-outlet /><sf-toast-outlet />`,
})
export class App {
  // Instantiated at startup so the stored theme is applied before the first screen.
  protected readonly theme = inject(ThemeService);
}
