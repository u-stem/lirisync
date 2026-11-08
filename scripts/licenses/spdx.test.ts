import { describe, expect, test } from "bun:test";
import { isAllowedExpression } from "./spdx";

const allowed = new Set(["MIT", "Apache-2.0", "BSD-3-Clause"]);

describe("isAllowedExpression", () => {
  test("accepts a single allowed id", () => {
    // Arrange
    const expression = "MIT";
    // Act
    const result = isAllowedExpression(expression, allowed);
    // Assert
    expect(result).toBe(true);
  });

  test("rejects a single disallowed id", () => {
    const result = isAllowedExpression("GPL-3.0-only", allowed);
    expect(result).toBe(false);
  });

  test("accepts OR when one side is allowed", () => {
    const result = isAllowedExpression("GPL-2.0-only OR MIT", allowed);
    expect(result).toBe(true);
  });

  test("rejects AND when one side is disallowed", () => {
    const result = isAllowedExpression("MIT AND GPL-3.0-only", allowed);
    expect(result).toBe(false);
  });

  test("accepts AND when both sides are allowed", () => {
    const result = isAllowedExpression("MIT AND BSD-3-Clause", allowed);
    expect(result).toBe(true);
  });

  test("binds AND tighter than OR", () => {
    const result = isAllowedExpression(
      "GPL-3.0-only AND MIT OR Apache-2.0",
      allowed,
    );
    expect(result).toBe(true);
  });

  test("respects parentheses", () => {
    const result = isAllowedExpression(
      "GPL-3.0-only AND (MIT OR Apache-2.0)",
      allowed,
    );
    expect(result).toBe(false);
  });

  test("accepts the legacy parenthesized npm form", () => {
    const result = isAllowedExpression("(MIT OR Apache-2.0)", allowed);
    expect(result).toBe(true);
  });

  test("rejects a WITH exception (needs manual review)", () => {
    const result = isAllowedExpression(
      "Apache-2.0 WITH LLVM-exception",
      allowed,
    );
    expect(result).toBe(false);
  });

  test("rejects an empty expression", () => {
    const result = isAllowedExpression("", allowed);
    expect(result).toBe(false);
  });

  test("rejects an unbalanced expression", () => {
    const result = isAllowedExpression("(MIT OR Apache-2.0", allowed);
    expect(result).toBe(false);
  });

  test("rejects a dangling operator", () => {
    const result = isAllowedExpression("MIT OR", allowed);
    expect(result).toBe(false);
  });

  test("rejects SEE LICENSE IN", () => {
    const result = isAllowedExpression("SEE LICENSE IN LICENSE.md", allowed);
    expect(result).toBe(false);
  });
});
