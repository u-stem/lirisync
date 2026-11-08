// Fails when a runtime (non-dev) npm dependency of any workspace package has a
// license outside scripts/allowed-licenses.json. Dev dependencies are not
// shipped, so they are not checked.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { isAllowedExpression } from "./spdx";

const repoRoot = resolve(import.meta.dir, "..", "..");

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readJson(path: string): Record<string, unknown> {
  const value: unknown = JSON.parse(readFileSync(path, "utf8"));
  if (!isRecord(value)) throw new Error(`Not a JSON object: ${path}`);
  return value;
}

function stringRecord(value: unknown): Record<string, string> {
  const result: Record<string, string> = {};
  if (!isRecord(value)) return result;
  for (const [key, entry] of Object.entries(value)) {
    if (typeof entry === "string") result[key] = entry;
  }
  return result;
}

function loadPolicy(): {
  allowed: Set<string>;
  overrides: Record<string, string>;
} {
  const policy = readJson(join(repoRoot, "scripts", "allowed-licenses.json"));
  const allowed = Array.isArray(policy.allowed)
    ? policy.allowed.filter((id): id is string => typeof id === "string")
    : [];
  return {
    allowed: new Set(allowed),
    overrides: stringRecord(policy.overrides),
  };
}

/** Node-style resolution: look in node_modules of fromDir and each ancestor. */
function resolvePackageDir(name: string, fromDir: string): string | null {
  let dir = fromDir;
  for (;;) {
    const candidate = join(dir, "node_modules", name, "package.json");
    if (existsSync(candidate)) return dirname(candidate);
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

function workspaceDirs(): string[] {
  const packagesDir = join(repoRoot, "packages");
  return readdirSync(packagesDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => join(packagesDir, entry.name))
    .filter((dir) => existsSync(join(dir, "package.json")));
}

function main(): number {
  const { allowed, overrides } = loadPolicy();
  const workspaceNames = new Set(
    workspaceDirs().map((dir) =>
      String(readJson(join(dir, "package.json")).name),
    ),
  );
  const queue: { name: string; fromDir: string }[] = [];
  for (const dir of workspaceDirs()) {
    const manifest = readJson(join(dir, "package.json"));
    for (const name of Object.keys(stringRecord(manifest.dependencies))) {
      queue.push({ name, fromDir: dir });
    }
  }

  const seen = new Set<string>();
  const failures: string[] = [];
  let checked = 0;
  for (let item = queue.shift(); item !== undefined; item = queue.shift()) {
    if (workspaceNames.has(item.name)) continue;
    const packageDir = resolvePackageDir(item.name, item.fromDir);
    if (packageDir === null) {
      failures.push(`${item.name}: not installed (run bun install)`);
      continue;
    }
    if (seen.has(packageDir)) continue;
    seen.add(packageDir);

    const manifest = readJson(join(packageDir, "package.json"));
    const label = `${item.name}@${String(manifest.version)}`;
    const license = overrides[`npm:${item.name}`] ?? manifest.license;
    checked += 1;
    if (typeof license !== "string" || !isAllowedExpression(license, allowed)) {
      failures.push(`${label}: ${JSON.stringify(license ?? null)}`);
    }
    for (const name of Object.keys(stringRecord(manifest.dependencies))) {
      queue.push({ name, fromDir: packageDir });
    }
  }

  for (const failure of failures)
    console.error(`disallowed license: ${failure}`);
  console.log(
    `npm licenses: ${checked} runtime packages checked, ${failures.length} failed`,
  );
  return failures.length === 0 ? 0 : 1;
}

process.exit(main());
