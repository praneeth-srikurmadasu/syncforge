import { DOCUMENT } from '@angular/common';
import { Injectable, computed, effect, inject, signal } from '@angular/core';

export type ThemePreference = 'dark' | 'light' | 'system';
const KEY = 'sf.theme';

/** Dark by default; light and "follow the system" are available. Stored per browser. */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly document = inject(DOCUMENT);
  private readonly media = this.document.defaultView?.matchMedia?.('(prefers-color-scheme: light)');
  private readonly systemLight = signal(this.media?.matches ?? false);

  readonly preference = signal<ThemePreference>(readPreference());
  readonly theme = computed<'dark' | 'light'>(() => {
    const pref = this.preference();
    if (pref === 'system') return this.systemLight() ? 'light' : 'dark';
    return pref;
  });

  constructor() {
    this.media?.addEventListener?.('change', (e) => this.systemLight.set(e.matches));
    effect(() => {
      this.document.documentElement.setAttribute('data-theme', this.theme());
    });
  }

  set(preference: ThemePreference): void {
    this.preference.set(preference);
    try {
      localStorage.setItem(KEY, preference);
    } catch {
      // not essential
    }
  }

  toggle(): void {
    this.set(this.theme() === 'dark' ? 'light' : 'dark');
  }
}

function readPreference(): ThemePreference {
  try {
    const value = localStorage.getItem(KEY);
    return value === 'light' || value === 'system' || value === 'dark' ? value : 'dark';
  } catch {
    return 'dark';
  }
}
