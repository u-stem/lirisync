import { describe, expect, test } from "bun:test";
import { parseWorkspacePattern } from "./workspaces";

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
