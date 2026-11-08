import { afterEach, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expandWorkspaces, parseWorkspacePattern } from "./workspaces";

describe("parseWorkspacePattern", () => {
  test("a trailing /* lists the children of a directory", () => {
    const result = parseWorkspacePattern("apps/*");
    expect(result).toEqual({ kind: "children", dir: "apps" });
  });

  test("a plain path is a single workspace", () => {
    const result = parseWorkspacePattern("tools/eval");
    expect(result).toEqual({ kind: "exact", dir: "tools/eval" });
  });

  test("a recursive glob is rejected", () => {
    const result = parseWorkspacePattern("packages/**");
    expect(result).toBeNull();
  });

  test("a glob in the middle is rejected", () => {
    const result = parseWorkspacePattern("packages/*/sub");
    expect(result).toBeNull();
  });

  test("a negated pattern is rejected", () => {
    const result = parseWorkspacePattern("!packages/legacy");
    expect(result).toBeNull();
  });

  test("a path leaving the repository is rejected", () => {
    const result = parseWorkspacePattern("../outside/*");
    expect(result).toBeNull();
  });
});

describe("expandWorkspaces", () => {
  const created: string[] = [];

  afterEach(() => {
    for (const root of created.splice(0)) {
      rmSync(root, { recursive: true, force: true });
    }
  });

  function makeRepo(): string {
    const root = mkdtempSync(join(tmpdir(), "lirisync-workspaces-"));
    created.push(root);
    mkdirSync(join(root, "packages", "core"), { recursive: true });
    writeFileSync(join(root, "packages", "core", "package.json"), "{}");
    mkdirSync(join(root, "packages", "notes"), { recursive: true });
    return root;
  }

  test("lists children that have a package.json", () => {
    const root = makeRepo();
    const result = expandWorkspaces(root, ["packages/*"]);
    expect(result).toEqual([join(root, "packages", "core")]);
  });

  test("throws when the workspaces field is not an array of strings", () => {
    const root = makeRepo();
    expect(() => expandWorkspaces(root, { packages: ["packages/*"] })).toThrow(
      "workspaces must be an array of strings",
    );
  });

  test("throws when a plain path has no package.json", () => {
    const root = makeRepo();
    expect(() => expandWorkspaces(root, ["packages/notes"])).toThrow(
      "Workspace has no package.json",
    );
  });

  test("throws when the parent of a /* pattern does not exist", () => {
    const root = makeRepo();
    expect(() => expandWorkspaces(root, ["apps/*"])).toThrow(
      "Workspace directory does not exist",
    );
  });

  test("throws when the patterns expand to no workspace", () => {
    const root = makeRepo();
    rmSync(join(root, "packages", "core"), { recursive: true });
    expect(() => expandWorkspaces(root, ["packages/*"])).toThrow(
      "workspaces expanded to no package",
    );
  });
});
