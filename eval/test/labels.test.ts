import { describe, expect, test } from "bun:test";
import { parseMs } from "@lirisync/core";
import { parseAudacityLabels } from "../src/labels";

describe("parseAudacityLabels", () => {
  test("reads a region label as the line's start time", () => {
    const text = "12.300000\t15.000000\t3\n";
    const result = parseAudacityLabels(text);
    expect(result).toEqual([{ line: 3, start: parseMs(12300) }]);
  });

  test("reads a point label (start equals end)", () => {
    const text = "1.000000\t1.000000\t1\n";
    const result = parseAudacityLabels(text);
    expect(result).toEqual([{ line: 1, start: parseMs(1000) }]);
  });

  test("accepts CRLF line endings", () => {
    const text = "1.0\t1.0\t1\r\n2.0\t2.0\t2\r\n";
    const result = parseAudacityLabels(text);
    expect(result).toHaveLength(2);
  });

  test("orders labels by lyric line number", () => {
    const text = "9.0\t9.0\t2\n1.0\t1.0\t1\n";
    const result = parseAudacityLabels(text).map((label) => label.line);
    expect(result).toEqual([1, 2]);
  });

  test("ignores blank rows", () => {
    const text = "\n1.0\t1.0\t1\n\n";
    const result = parseAudacityLabels(text);
    expect(result).toHaveLength(1);
  });

  test("rejects a label that is not a line number", () => {
    const text = "1.0\t1.0\tchorus\n";
    expect(() => parseAudacityLabels(text)).toThrow("row 1");
  });

  test("rejects line number zero", () => {
    const text = "1.0\t1.0\t0\n";
    expect(() => parseAudacityLabels(text)).toThrow("line number");
  });

  test("rejects a spectral selection row", () => {
    const text = "1.0\t2.0\t1\n\\\t100.0\t2000.0\n";
    expect(() => parseAudacityLabels(text)).toThrow("row 2");
  });

  test("rejects an end before the start", () => {
    const text = "2.0\t1.0\t1\n";
    expect(() => parseAudacityLabels(text)).toThrow("end before start");
  });

  test("rejects the same line labeled twice", () => {
    const text = "1.0\t1.0\t1\n5.0\t5.0\t1\n";
    expect(() => parseAudacityLabels(text)).toThrow("labeled twice");
  });
});
