import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import type { EChartsCoreOption } from 'echarts/core';
import { NgxEchartsDirective } from 'ngx-echarts';
import { ThemeService } from '../../core/theme/theme.service';

export type ChartTone = 'accent' | 'success' | 'danger' | 'warning' | 'info' | 'neutral';

export interface ChartSeries {
  name: string;
  values: number[];
  tone: ChartTone;
}

/** Reads a design token from the document, so charts follow the active theme. */
function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

const TONE_TOKENS: Record<ChartTone, string> = {
  accent: '--sf-accent',
  success: '--sf-success',
  danger: '--sf-danger',
  warning: '--sf-warning',
  info: '--sf-info',
  neutral: '--sf-text-faint',
};

/**
 * Bar chart over categories (days, statuses, departments). Thin bars with rounded data
 * ends, recessive axes, a hover tooltip, a legend for two or more series, and the numbers
 * repeated in a visually hidden table for screen readers.
 */
@Component({
  selector: 'sf-bar-chart',
  imports: [NgxEchartsDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="plot"
      echarts
      [options]="options()"
      [autoResize]="true"
      [style.height.px]="height()"
      role="img"
      [attr.aria-label]="summary()"
    ></div>
    <table class="sf-visually-hidden">
      <caption>
        {{
          summary()
        }}
      </caption>
      <thead>
        <tr>
          <th scope="col">{{ categoryLabel() }}</th>
          @for (s of series(); track s.name) {
            <th scope="col">{{ s.name }}</th>
          }
        </tr>
      </thead>
      <tbody>
        @for (c of categories(); track $index; let i = $index) {
          <tr>
            <th scope="row">{{ c }}</th>
            @for (s of series(); track s.name) {
              <td>{{ s.values[i] }}</td>
            }
          </tr>
        }
      </tbody>
    </table>
  `,
  styles: `
    :host {
      display: block;
      position: relative;
    }
    .plot {
      width: 100%;
    }
  `,
})
export class BarChartComponent {
  private readonly theme = inject(ThemeService);

  readonly categories = input.required<string[]>();
  readonly series = input.required<ChartSeries[]>();
  readonly stacked = input(false);
  readonly horizontal = input(false);
  readonly height = input(220);
  readonly categoryLabel = input('Category');
  readonly summary = input('Bar chart');

  protected readonly options = computed<EChartsCoreOption>(() => {
    this.theme.theme(); // rebuild with the new token values when the theme changes
    const text = token('--sf-text-muted');
    const faint = token('--sf-text-faint');
    const grid = token('--sf-border');
    const surface = token('--sf-surface-raised');
    const ink = token('--sf-text');
    const series = this.series();
    const horizontal = this.horizontal();
    const stacked = this.stacked();
    const radius = horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0];

    const categoryAxis = {
      type: 'category',
      data: this.categories(),
      axisLine: { lineStyle: { color: grid } },
      axisTick: { show: false },
      axisLabel: { color: text, fontSize: 11, hideOverlap: true },
    };
    const valueAxis = {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: grid, type: 'dashed' } },
      axisLabel: { color: faint, fontSize: 11 },
    };

    return {
      animationDuration: 300,
      textStyle: { fontFamily: token('--sf-font-sans') },
      grid: { left: 8, right: 12, top: series.length > 1 ? 32 : 12, bottom: 4, containLabel: true },
      legend:
        series.length > 1
          ? {
              top: 0,
              left: 0,
              icon: 'roundRect',
              itemWidth: 10,
              itemHeight: 10,
              textStyle: { color: text, fontSize: 12 },
            }
          : undefined,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow', shadowStyle: { color: token('--sf-neutral-soft') } },
        backgroundColor: surface,
        borderColor: grid,
        textStyle: { color: ink, fontSize: 12 },
      },
      xAxis: horizontal ? valueAxis : categoryAxis,
      yAxis: horizontal ? { ...categoryAxis, inverse: true } : valueAxis,
      series: series.map((s, index) => ({
        name: s.name,
        type: 'bar',
        data: s.values,
        stack: stacked ? 'total' : undefined,
        barMaxWidth: 22,
        barGap: '20%',
        itemStyle: {
          color: token(TONE_TOKENS[s.tone]),
          // only the top segment of a stack gets the rounded data end
          borderRadius: !stacked || index === series.length - 1 ? radius : 0,
          borderColor: token('--sf-surface'),
          borderWidth: stacked ? 1 : 0,
        },
        emphasis: { focus: 'series' },
      })),
    };
  });
}
