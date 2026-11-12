import { FormControl, FormGroup, ValidatorFn, Validators } from '@angular/forms';

/**
 * Form fields generated from a connector type's JSON schema (config_schema and
 * credentials_schema in GET /connector-types), so new connector types need no new UI code.
 * Only the schema features the backend uses are read: string / integer / boolean, enum,
 * nullable via anyOf, required, default, description, min/max length and value, format.
 */
export type FieldKind = 'text' | 'secret' | 'url' | 'integer' | 'boolean' | 'select';

export interface SchemaField {
  name: string;
  label: string;
  kind: FieldKind;
  required: boolean;
  description: string | null;
  defaultValue: string | number | boolean | null;
  options: string[];
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
}

interface JsonSchema {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  format?: string;
  enum?: unknown[];
  anyOf?: JsonSchema[];
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  writeOnly?: boolean;
  properties?: Record<string, JsonSchema>;
  required?: string[];
}

export function schemaFields(schema: unknown): SchemaField[] {
  const root = (schema ?? {}) as JsonSchema;
  const required = new Set(root.required ?? []);
  return Object.entries(root.properties ?? {}).map(([name, prop]) => {
    // `anyOf: [{...}, {type: 'null'}]` is how Pydantic writes an optional value.
    const concrete = prop.anyOf?.find((p) => p.type !== 'null') ?? prop;
    let kind: FieldKind = 'text';
    if (concrete.enum?.length) kind = 'select';
    else if (concrete.type === 'integer' || concrete.type === 'number') kind = 'integer';
    else if (concrete.type === 'boolean') kind = 'boolean';
    else if (concrete.format === 'password' || concrete.writeOnly) kind = 'secret';
    else if (concrete.format === 'uri') kind = 'url';
    return {
      name,
      label: prop.title ?? name,
      kind,
      required: required.has(name),
      description: prop.description ?? null,
      defaultValue: (prop.default ?? null) as SchemaField['defaultValue'],
      options: (concrete.enum ?? []).map(String),
      minLength: concrete.minLength,
      maxLength: concrete.maxLength,
      minimum: concrete.minimum,
      maximum: concrete.maximum,
    };
  });
}

/** Turns form values into the JSON body: empty optional values are left out. */
export function fieldValues(
  fields: SchemaField[],
  raw: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const value = raw[f.name];
    if (f.kind === 'boolean') {
      out[f.name] = !!value;
      continue;
    }
    if (value === null || value === undefined || value === '') continue;
    out[f.name] = f.kind === 'integer' ? Number(value) : String(value).trim();
  }
  return out;
}

/** A FormGroup for the fields, pre-filled from `values` (or the schema defaults). */
export function buildGroup(fields: SchemaField[], values: Record<string, unknown> = {}): FormGroup {
  const controls: Record<string, FormControl> = {};
  for (const f of fields) {
    const validators: ValidatorFn[] = [];
    if (f.required && f.kind !== 'boolean') validators.push(Validators.required);
    if (f.minLength !== undefined) validators.push(Validators.minLength(f.minLength));
    if (f.maxLength !== undefined) validators.push(Validators.maxLength(f.maxLength));
    if (f.minimum !== undefined) validators.push(Validators.min(f.minimum));
    if (f.maximum !== undefined) validators.push(Validators.max(f.maximum));
    const initial = f.name in values ? values[f.name] : f.defaultValue;
    controls[f.name] = new FormControl(
      f.kind === 'boolean' ? !!initial : (initial ?? ''),
      validators,
    );
  }
  return new FormGroup(controls);
}
