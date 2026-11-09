import { describe, expect, test } from "bun:test";
import type { AnchoredLine } from "@lirisync/core";
import { parseMs } from "@lirisync/core";
import {
  assertLabeledLinesSung,
  stageOneConfidence,
  toPredictions,
} from "../src/predictions";

const anchor: AnchoredLine = {
  status: "anchor",
  start: parseMs(1200),
  end: parseMs(3400),
  matchRatio: 0.75,
  ambiguous: false,
};

describe("toPredictions", () => {
  test("numbers lines from 1", () => {
    const result = toPredictions([anchor]);
    expect(result[0]?.line).toBe(1);
  });

  test("keeps an anchor's start", () => {
    const result = toPredictions([anchor]);
    expect(result[0]?.start).toBe(parseMs(1200));
  });

  test("gives an anchor its stage-one confidence", () => {
    const result = toPredictions([anchor]);
    expect(result[0]?.confidence).toBe(stageOneConfidence(anchor));
  });

  test("leaves an unmatched line without a start", () => {
    const lines: AnchoredLine[] = [
      { status: "unmatched", matchRatio: 0.1, ambiguous: false },
    ];
    expect(toPredictions(lines)).toEqual([{ line: 1, start: null }]);
  });

  test("leaves a not-sung line without a start", () => {
    const lines: AnchoredLine[] = [anchor, { status: "not_sung" }];
    expect(toPredictions(lines)[1]).toEqual({ line: 2, start: null });
  });
});

describe("stageOneConfidence", () => {
  test("is the match ratio", () => {
    expect(stageOneConfidence(anchor)).toBe(0.75);
  });
});

describe("assertLabeledLinesSung", () => {
  const notSung: AnchoredLine = { status: "not_sung" };
  const truth = (...lines: number[]) =>
    lines.map((line) => ({ line, start: parseMs(line * 1000) }));

  test("accepts labels on anchored lines", () => {
    expect(() => assertLabeledLinesSung(truth(1), [anchor])).not.toThrow();
  });

  test("accepts a not-sung line that has no label", () => {
    const lines = [anchor, notSung];
    expect(() => assertLabeledLinesSung(truth(1), lines)).not.toThrow();
  });

  test("names a labeled line the worker reports as not sung", () => {
    const lines = [anchor, notSung];
    expect(() => assertLabeledLinesSung(truth(1, 2), lines)).toThrow("line 2");
  });

  test("names every such line", () => {
    const lines = [notSung, anchor, notSung];
    expect(() => assertLabeledLinesSung(truth(1, 2, 3), lines)).toThrow(
      "lines 1, 3",
    );
  });
});
