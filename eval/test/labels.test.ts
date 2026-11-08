import { describe, expect, test } from "bun:test";
import { parseMs } from "@lirisync/core";
import { assertLabelsSung, parseAudacityLabels } from "../src/labels";

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

  test("names the row without an Error prefix", () => {
    const text = "1.0\t1.0\t1\n1,0\t1.0\t2\n";
    expect(() => parseAudacityLabels(text)).toThrow(/^row 2: Expected/);
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

describe("assertLabelsSung", () => {
  const lyrics = "first\n\nthird\n";

  test("accepts labels on non-blank lyric lines", () => {
    const labels = parseAudacityLabels("1.0\t1.0\t1\n3.0\t3.0\t3\n");
    expect(() => assertLabelsSung(labels, lyrics)).not.toThrow();
  });

  test("rejects a label on a blank line", () => {
    const labels = parseAudacityLabels("2.0\t2.0\t2\n");
    expect(() => assertLabelsSung(labels, lyrics)).toThrow("line 2 is blank");
  });

  test("a trailing newline does not add a line", () => {
    const labels = parseAudacityLabels("4.0\t4.0\t4\n");
    expect(() => assertLabelsSung(labels, lyrics)).toThrow(
      "line 4 is past the end of lyrics.txt (3 lines)",
    );
  });

  test("rejects a label past the last lyric line", () => {
    const labels = parseAudacityLabels("9.0\t9.0\t9\n");
    expect(() => assertLabelsSung(labels, lyrics)).toThrow(
      "line 9 is past the end",
    );
  });
});
