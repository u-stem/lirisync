import { describe, expect, test } from "bun:test";
import { parseSecondsText } from "../src/seconds";

describe("parseSecondsText", () => {
  test("reads whole seconds", () => {
    const input = "12";
    const result: number = parseSecondsText(input);
    expect(result).toBe(12000);
  });

  test("reads Audacity's six decimal places", () => {
    const input = "4.100000";
    const result: number = parseSecondsText(input);
    expect(result).toBe(4100);
  });

  test("rounds a half millisecond up", () => {
    const input = "1.2345";
    const result: number = parseSecondsText(input);
    expect(result).toBe(1235);
  });

  test("rounds below a half millisecond down", () => {
    const input = "1.234499";
    const result: number = parseSecondsText(input);
    expect(result).toBe(1234);
  });

  test("carries a rounded-up millisecond into the next second", () => {
    const input = "0.9996";
    const result: number = parseSecondsText(input);
    expect(result).toBe(1000);
  });

  test("rejects a negative value", () => {
    const input = "-0.5";
    expect(() => parseSecondsText(input)).toThrow("seconds");
  });

  test("rejects a comma as the decimal separator", () => {
    const input = "1,5";
    expect(() => parseSecondsText(input)).toThrow("seconds");
  });

  test("rejects exponent notation", () => {
    const input = "1e3";
    expect(() => parseSecondsText(input)).toThrow("seconds");
  });
});
