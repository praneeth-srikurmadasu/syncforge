import { Employee } from '../../core/api/models';
import { groupByManager, visibleRows } from './reporting-tree';

function emp(
  id: string,
  manager: string | null,
  status: Employee['employment_status'] = 'active',
): Employee {
  return {
    id,
    full_name: id.toUpperCase(),
    first_name: id,
    last_name: id,
    email: `${id}@example.com`,
    employee_number: id,
    employment_status: status,
    manager: manager ? { id: manager, full_name: manager, employee_number: manager } : null,
    department: null,
    designation: null,
    location: null,
    joining_date: '2026-01-01',
    termination_date: null,
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    organization_id: 'o',
    version: 1,
  };
}

describe('reporting tree', () => {
  const people = [
    emp('ceo', null),
    emp('vp', 'ceo'),
    emp('eng', 'vp'),
    emp('ops', 'ceo'),
    emp('gone', 'ceo', 'terminated'),
  ];

  it('nests people under their managers, depth first', () => {
    const rows = visibleRows(groupByManager(people), new Set());
    expect(rows.map((r) => [r.employee.id, r.depth, r.reports])).toEqual([
      ['ceo', 0, 2],
      ['vp', 1, 1],
      ['eng', 2, 0],
      ['ops', 1, 0],
    ]);
  });

  it('hides a collapsed team', () => {
    const rows = visibleRows(groupByManager(people), new Set(['vp']));
    expect(rows.map((r) => r.employee.id)).toEqual(['ceo', 'vp', 'ops']);
  });

  it('puts people whose manager was not loaded at the top level', () => {
    const rows = visibleRows(groupByManager([emp('a', 'not-loaded'), emp('b', 'a')]), new Set());
    expect(rows.map((r) => [r.employee.id, r.depth])).toEqual([
      ['a', 0],
      ['b', 1],
    ]);
  });
});
