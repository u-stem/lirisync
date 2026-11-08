// Fails when a runtime (dependencies / optionalDependencies) npm package of any
// workspace listed in the root package.json has a
// license outside scripts/allowed-licenses.json. Dev dependencies are not
// shipped, so they are not checked.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { isAllowedExpression } from "./spdx";
import { expandWorkspaces } from "./workspaces";

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

/** Runtime dependency names: dependencies plus optionalDependencies. */
function runtimeDependencies(manifest: Record<string, unknown>): {
  required: string[];
  optional: string[];
} {
  return {
    required: Object.keys(stringRecord(manifest.dependencies)),
    optional: Object.keys(stringRecord(manifest.optionalDependencies)),
  };
}

type QueueItem = { name: string; fromDir: string; optional: boolean };

function enqueue(
  queue: QueueItem[],
  manifest: Record<string, unknown>,
  fromDir: string,
): void {
  const { required, optional } = runtimeDependencies(manifest);
  for (const name of required) queue.push({ name, fromDir, optional: false });
  for (const name of optional) queue.push({ name, fromDir, optional: true });
}

function main(): number {
  const { allowed, overrides } = loadPolicy();
  const rootManifest = readJson(join(repoRoot, "package.json"));
  const patterns = Array.isArray(rootManifest.workspaces)
    ? rootManifest.workspaces.filter(
        (pattern): pattern is string => typeof pattern === "string",
      )
    : [];
  const workspaces = expandWorkspaces(repoRoot, patterns).map((dir) => ({
    dir,
    manifest: readJson(join(dir, "package.json")),
  }));
  const workspaceNames = new Set(
    workspaces.map(({ manifest }) => String(manifest.name)),
  );
  const queue: QueueItem[] = [];
  for (const { dir, manifest } of workspaces) enqueue(queue, manifest, dir);

  const seen = new Set<string>();
  const failures: string[] = [];
  let checked = 0;
  for (let item = queue.shift(); item !== undefined; item = queue.shift()) {
    if (workspaceNames.has(item.name)) continue;
    const packageDir = resolvePackageDir(item.name, item.fromDir);
    if (packageDir === null) {
      // Optional dependencies are often per-platform binaries for other OSes.
      if (!item.optional) {
        failures.push(`${item.name}: not installed (run bun install)`);
      }
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
    enqueue(queue, manifest, packageDir);
  }

  for (const failure of failures)
    console.error(`license check failed: ${failure}`);
  console.log(
    `npm licenses: ${workspaces.length} workspaces, ${checked} runtime packages checked, ${failures.length} failed`,
  );
  return failures.length === 0 ? 0 : 1;
}

process.exit(main());
