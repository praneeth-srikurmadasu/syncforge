import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import {
  Activity,
  ArrowLeft,
  Building2,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleX,
  Clock,
  Copy,
  Eye,
  EyeOff,
  Cable,
  FileClock,
  GitCompareArrows,
  GitMerge,
  Inbox,
  Info,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  Moon,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Play,
  Plug,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Settings,
  ShieldCheck,
  ShieldAlert,
  Sun,
  Trash2,
  TriangleAlert,
  UserMinus,
  UserPlus,
  Users,
  Workflow,
  X,
  Zap,
  Archive,
  Power,
  KeyRound,
  ArrowUp,
  ArrowDown,
  type IconNode,
} from 'lucide';

/** Curated Lucide icons (ISC licence), rendered as inline SVG. */
const ICONS = {
  activity: Activity,
  archive: Archive,
  'arrow-down': ArrowDown,
  'arrow-left': ArrowLeft,
  'arrow-up': ArrowUp,
  building: Building2,
  cable: Cable,
  check: Check,
  'chevron-down': ChevronDown,
  'chevron-left': ChevronLeft,
  'chevron-right': ChevronRight,
  'circle-alert': CircleAlert,
  'circle-check': CircleCheck,
  'circle-x': CircleX,
  clock: Clock,
  compare: GitCompareArrows,
  copy: Copy,
  eye: Eye,
  'eye-off': EyeOff,
  'file-clock': FileClock,
  inbox: Inbox,
  info: Info,
  key: KeyRound,
  dashboard: LayoutDashboard,
  'list-checks': ListChecks,
  'log-out': LogOut,
  menu: Menu,
  merge: GitMerge,
  moon: Moon,
  network: Network,
  'panel-close': PanelLeftClose,
  'panel-open': PanelLeftOpen,
  pencil: Pencil,
  play: Play,
  plug: Plug,
  plus: Plus,
  power: Power,
  refresh: RefreshCw,
  replay: RotateCcw,
  search: Search,
  settings: Settings,
  shield: ShieldCheck,
  'shield-alert': ShieldAlert,
  sun: Sun,
  trash: Trash2,
  warning: TriangleAlert,
  'user-minus': UserMinus,
  'user-plus': UserPlus,
  users: Users,
  workflow: Workflow,
  x: X,
  zap: Zap,
} satisfies Record<string, IconNode>;

export type IconName = keyof typeof ICONS;

@Component({
  selector: 'sf-icon',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'sf-icon', 'aria-hidden': 'true' },
  template: `
    <svg
      xmlns="http://www.w3.org/2000/svg"
      [attr.width]="size()"
      [attr.height]="size()"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      [attr.stroke-width]="strokeWidth()"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      @for (node of nodes(); track $index) {
        @switch (node[0]) {
          @case ('path') {
            <svg:path [attr.d]="node[1]['d']" />
          }
          @case ('circle') {
            <svg:circle
              [attr.cx]="node[1]['cx']"
              [attr.cy]="node[1]['cy']"
              [attr.r]="node[1]['r']"
            />
          }
          @case ('rect') {
            <svg:rect
              [attr.x]="node[1]['x']"
              [attr.y]="node[1]['y']"
              [attr.width]="node[1]['width']"
              [attr.height]="node[1]['height']"
              [attr.rx]="node[1]['rx']"
              [attr.ry]="node[1]['ry']"
            />
          }
          @case ('line') {
            <svg:line
              [attr.x1]="node[1]['x1']"
              [attr.y1]="node[1]['y1']"
              [attr.x2]="node[1]['x2']"
              [attr.y2]="node[1]['y2']"
            />
          }
          @case ('polyline') {
            <svg:polyline [attr.points]="node[1]['points']" />
          }
          @case ('polygon') {
            <svg:polygon [attr.points]="node[1]['points']" />
          }
          @case ('ellipse') {
            <svg:ellipse
              [attr.cx]="node[1]['cx']"
              [attr.cy]="node[1]['cy']"
              [attr.rx]="node[1]['rx']"
              [attr.ry]="node[1]['ry']"
            />
          }
        }
      }
    </svg>
  `,
  styles: `
    :host {
      display: inline-flex;
      flex-shrink: 0;
      line-height: 0;
    }
  `,
})
export class IconComponent {
  readonly name = input.required<IconName>();
  readonly size = input(16);
  readonly strokeWidth = input(1.8);
  protected readonly nodes = computed(
    () => ICONS[this.name()] as unknown as [string, Record<string, string | number>][],
  );
}
