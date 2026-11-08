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

/** Directories (absolute) of every workspace that has a package.json. */
export function expandWorkspaces(
  repoRoot: string,
  patterns: readonly string[],
): string[] {
  const dirs: string[] = [];
  for (const raw of patterns) {
    const pattern = parseWorkspacePattern(raw);
    if (pattern === null) {
      throw new Error(`Unsupported workspace pattern: ${raw}`);
    }
    const base = join(repoRoot, pattern.dir);
    const candidates =
      pattern.kind === "exact"
        ? [base]
        : existsSync(base)
          ? readdirSync(base, { withFileTypes: true })
              .filter((entry) => entry.isDirectory())
              .map((entry) => join(base, entry.name))
          : [];
    for (const dir of candidates) {
      if (existsSync(join(dir, "package.json"))) dirs.push(dir);
    }
  }
  return dirs;
}
