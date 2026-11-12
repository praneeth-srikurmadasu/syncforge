import { Employee } from '../../core/api/models';

export interface TreeRow {
  employee: Employee;
  depth: number;
  reports: number;
}

/** Groups current (not terminated) employees by manager; unknown managers count as none. */
export function groupByManager(employees: Employee[]): Map<string | null, Employee[]> {
  const current = employees.filter((e) => e.employment_status !== 'terminated');
  const ids = new Set(current.map((e) => e.id));
  const byManager = new Map<string | null, Employee[]>();
  for (const e of current) {
    const key = e.manager && ids.has(e.manager.id) ? e.manager.id : null;
    byManager.set(key, [...(byManager.get(key) ?? []), e]);
  }
  return byManager;
}

/** Depth-first rows for display; collapsed managers hide their teams. */
export function visibleRows(
  byManager: Map<string | null, Employee[]>,
  collapsed: ReadonlySet<string>,
): TreeRow[] {
  const rows: TreeRow[] = [];
  const visit = (managerId: string | null, depth: number, seen: ReadonlySet<string>) => {
    for (const e of byManager.get(managerId) ?? []) {
      if (seen.has(e.id)) continue; // defensive: the API prevents reporting cycles
      const reports = byManager.get(e.id)?.length ?? 0;
      rows.push({ employee: e, depth, reports });
      if (reports && !collapsed.has(e.id)) visit(e.id, depth + 1, new Set([...seen, e.id]));
    }
  };
  visit(null, 0, new Set());
  return rows;
}
