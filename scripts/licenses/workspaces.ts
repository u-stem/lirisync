import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

export type WorkspacePattern =
  | { kind: "children"; dir: string }
  | { kind: "exact"; dir: string };

const SAFE_PATH = /^[A-Za-z0-9._-]+(\/[A-Za-z0-9._-]+)*$/;

/**
 * Supports only `<dir>/*` and plain `<dir>` patterns. Anything else (recursive
 * globs, negation, paths leaving the repo) returns null so the caller fails
 * loudly instead of silently skipping packages.
 */
export function parseWorkspacePattern(
  pattern: string,
): WorkspacePattern | null {
  const children = pattern.endsWith("/*");
  const dir = children ? pattern.slice(0, -2) : pattern;
  if (!SAFE_PATH.test(dir) || dir.split("/").some((part) => part === "..")) {
    return null;
  }
  return children ? { kind: "children", dir } : { kind: "exact", dir };
}

function isStringArray(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
  );
}

/**
 * Directories (absolute) of every workspace. Throws instead of returning a
 * partial list: a non-array `workspaces` field (e.g. `{ packages: [...] }`), a
 * plain path without package.json, a missing `<dir>` for `<dir>/*`, or an
 * empty result would otherwise let the license check pass on nothing.
 */
export function expandWorkspaces(
  repoRoot: string,
  workspaces: unknown,
): string[] {
  if (!isStringArray(workspaces)) {
    throw new Error("root package.json workspaces must be an array of strings");
  }
  const dirs: string[] = [];
  for (const raw of workspaces) {
    const pattern = parseWorkspacePattern(raw);
    if (pattern === null) {
      throw new Error(`Unsupported workspace pattern: ${raw}`);
    }
    const base = join(repoRoot, pattern.dir);
    if (pattern.kind === "exact") {
      if (!existsSync(join(base, "package.json"))) {
        throw new Error(`Workspace has no package.json: ${raw}`);
      }
      dirs.push(base);
      continue;
    }
    if (!existsSync(base)) {
      throw new Error(`Workspace directory does not exist: ${raw}`);
    }
    for (const entry of readdirSync(base, { withFileTypes: true })) {
      const dir = join(base, entry.name);
      if (entry.isDirectory() && existsSync(join(dir, "package.json"))) {
        dirs.push(dir);
      }
    }
  }
  if (dirs.length === 0) {
    throw new Error("workspaces expanded to no package");
  }
  return dirs;
}
