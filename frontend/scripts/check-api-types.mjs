// Fails if src/app/core/api/schema.d.ts no longer matches openapi/openapi.json.
// Refresh the snapshot from the backend first (see README.md), then run `npm run api:types`.
import { execSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const dir = mkdtempSync(join(tmpdir(), 'sf-api-'));
const out = join(dir, 'schema.d.ts');
try {
  // One command string (no argument array) works with npx on Windows and Linux alike.
  execSync(`npx --yes openapi-typescript@7.13.0 openapi/openapi.json -o "${out}"`, {
    stdio: 'inherit',
  });
  const fresh = readFileSync(out, 'utf8').replace(/\r\n/g, '\n');
  const current = readFileSync('src/app/core/api/schema.d.ts', 'utf8').replace(/\r\n/g, '\n');
  if (fresh !== current) {
    console.error('API types are out of date: run `npm run api:types` and commit the result.');
    process.exit(1);
  }
  console.log('API types match openapi/openapi.json.');
} finally {
  rmSync(dir, { recursive: true, force: true });
}
