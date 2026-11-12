import { fieldValues, schemaFields } from './schema-fields';

const CONFIG = {
  properties: {
    base_url: {
      anyOf: [{ type: 'string', format: 'uri', maxLength: 2083 }, { type: 'null' }],
      default: null,
      title: 'Base Url',
      description: 'Override the default endpoint.',
    },
    rate_limit_per_minute: {
      anyOf: [{ type: 'integer', minimum: 1, maximum: 10000 }, { type: 'null' }],
      default: null,
      title: 'Rate Limit Per Minute',
    },
    customer: { type: 'string', default: 'my_customer', title: 'Customer', maxLength: 100 },
  },
};
const CREDS = {
  properties: {
    client_id: { type: 'string', title: 'Client Id', minLength: 3 },
    client_secret: { type: 'string', format: 'password', writeOnly: true, title: 'Client Secret' },
  },
  required: ['client_id', 'client_secret'],
};

describe('schemaFields', () => {
  it('reads optional, typed and defaulted config fields', () => {
    const fields = schemaFields(CONFIG);
    expect(fields.map((f) => [f.name, f.kind, f.required])).toEqual([
      ['base_url', 'url', false],
      ['rate_limit_per_minute', 'integer', false],
      ['customer', 'text', false],
    ]);
    expect(fields[1].maximum).toBe(10000);
    expect(fields[2].defaultValue).toBe('my_customer');
  });

  it('marks write-only credentials as secrets and keeps required', () => {
    const fields = schemaFields(CREDS);
    expect(fields.map((f) => [f.name, f.kind, f.required])).toEqual([
      ['client_id', 'text', true],
      ['client_secret', 'secret', true],
    ]);
  });

  it('drops empty optional values and converts numbers', () => {
    const fields = schemaFields(CONFIG);
    expect(
      fieldValues(fields, { base_url: '', rate_limit_per_minute: '30', customer: ' acme ' }),
    ).toEqual({
      rate_limit_per_minute: 30,
      customer: 'acme',
    });
  });
});
