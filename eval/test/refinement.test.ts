import { describe, expect, test } from "bun:test";
import { type AnchoredLine, parseMs, type RefinedLine } from "@lirisync/core";
import {
  addStatusCounts,
  countStatuses,
  formatStatusCounts,
  refinedConfidence,
  toRefinedPredictions,
  windowsFromAnchors,
} from "../src/refinement";

const anchor: AnchoredLine = {
  status: "anchor",
  start: parseMs(1200),
  end: parseMs(3400),
  matchRatio: 0.75,
  ambiguous: false,
};
const unmatched: AnchoredLine = {
  status: "unmatched",
  matchRatio: 0.1,
  ambiguous: false,
};
const notSung: AnchoredLine = { status: "not_sung" };

const refined: RefinedLine = {
  status: "refined",
  start: parseMs(1300),
  end: parseMs(3300),
  logRatio: -0.5,
  skippedChars: 2,
};
const tooShort: RefinedLine = { status: "too_short", skippedChars: 1 };

describe("windowsFromAnchors", () => {
  test("gives an anchor its start and end", () => {
    expect(windowsFromAnchors([anchor])).toEqual([
      { start: parseMs(1200), end: parseMs(3400) },
    ]);
  });

  test("gives an unmatched line no window", () => {
    expect(windowsFromAnchors([unmatched])).toEqual([null]);
  });

  test("gives a line that is not sung no window", () => {
    expect(windowsFromAnchors([notSung])).toEqual([null]);
  });

  test("keeps one entry per line", () => {
    expect(windowsFromAnchors([unmatched, anchor, notSung])).toHaveLength(3);
  });

  test("moves the start later by the shift", () => {
    expect(windowsFromAnchors([anchor], 700)).toEqual([
      { start: parseMs(1900), end: parseMs(3400) },
    ]);
  });

  test("does not move the start past the end", () => {
    expect(windowsFromAnchors([anchor], 5000)[0]?.start).toBe(parseMs(3400));
  });

  test("does not move the start before 0", () => {
    expect(windowsFromAnchors([anchor], -2000)[0]?.start).toBe(parseMs(0));
  });
});

describe("refinedConfidence", () => {
  test("is 1 for a log ratio of 0", () => {
    expect(refinedConfidence(0)).toBe(1);
  });

  test("is the exponential of the log ratio", () => {
    expect(refinedConfidence(-1)).toBeCloseTo(Math.exp(-1), 12);
  });

  test("stays inside 0 to 1 for a very low log ratio", () => {
    expect(refinedConfidence(-1000)).toBe(0);
  });
});

describe("toRefinedPredictions", () => {
  test("shifts a refined line's start by the offset", () => {
    const result = toRefinedPredictions([anchor], [refined], -100);
    expect(result[0]?.start).toBe(parseMs(1200));
  });

  test("does not shift a start before 0", () => {
    const result = toRefinedPredictions([anchor], [refined], -5000);
    expect(result[0]?.start).toBe(parseMs(0));
  });

  test("does not shift a line that fell back to stage 1", () => {
    const result = toRefinedPredictions([anchor], [tooShort], -100);
    expect(result[0]?.start).toBe(parseMs(1200));
  });

  test("numbers lines from 1", () => {
    const result = toRefinedPredictions([anchor], [refined]);
    expect(result[0]?.line).toBe(1);
  });

  test("takes a refined line's start from the second stage", () => {
    const result = toRefinedPredictions([anchor], [refined]);
    expect(result[0]?.start).toBe(parseMs(1300));
  });

  test("gives a refined line the exponential of its log ratio", () => {
    const result = toRefinedPredictions([anchor], [refined]);
    expect(result[0]?.confidence).toBeCloseTo(Math.exp(-0.5), 12);
  });

  test("returns a line the second stage skipped to the first stage's start", () => {
    const result = toRefinedPredictions([anchor], [tooShort]);
    expect(result[0]?.start).toBe(parseMs(1200));
  });

  test("gives a returned line confidence 0", () => {
    const result = toRefinedPredictions([anchor], [tooShort]);
    expect(result[0]?.confidence).toBe(0);
  });

  test.each(["no_text", "too_long"] as const)(
    "returns a %s line to the first stage's start",
    (status) => {
      const result = toRefinedPredictions(
        [anchor],
        [{ status, skippedChars: 0 }],
      );
      expect(result[0]).toEqual({
        line: 1,
        start: parseMs(1200),
        confidence: 0,
      });
    },
  );

  test("leaves an unmatched line without a start", () => {
    const result = toRefinedPredictions(
      [unmatched],
      [{ status: "no_window", skippedChars: 0 }],
    );
    expect(result).toEqual([{ line: 1, start: null }]);
  });

  test("leaves a line that is not sung without a start", () => {
    const result = toRefinedPredictions(
      [notSung],
      [{ status: "no_window", skippedChars: 0 }],
    );
    expect(result).toEqual([{ line: 1, start: null }]);
  });

  test("keeps the order of lines", () => {
    const result = toRefinedPredictions(
      [unmatched, anchor],
      [{ status: "no_window", skippedChars: 0 }, refined],
    );
    expect(result.map(({ line }) => line)).toEqual([1, 2]);
  });

  test("throws when the stages disagree on the number of lines", () => {
    expect(() => toRefinedPredictions([anchor], [])).toThrow("1 lines");
  });
});

describe("countStatuses", () => {
  test("counts lines by status", () => {
    const counts = countStatuses([
      refined,
      refined,
      tooShort,
      { status: "no_window", skippedChars: 0 },
    ]);
    expect(counts).toEqual({
      refined: 2,
      no_window: 1,
      no_text: 0,
      too_long: 0,
      too_short: 1,
      skippedChars: 5,
    });
  });

  test("is all zeros for no lines", () => {
    expect(countStatuses([])).toEqual({
      refined: 0,
      no_window: 0,
      no_text: 0,
      too_long: 0,
      too_short: 0,
      skippedChars: 0,
    });
  });
});

describe("addStatusCounts", () => {
  test("sums every field over the songs", () => {
    const total = addStatusCounts([
      countStatuses([refined, tooShort]),
      countStatuses([refined]),
    ]);
    expect(total).toEqual({
      refined: 2,
      no_window: 0,
      no_text: 0,
      too_long: 0,
      too_short: 1,
      skippedChars: 5,
    });
  });
});

describe("formatStatusCounts", () => {
  test("lists a row per song and the total", () => {
    const text = formatStatusCounts([
      { slug: "a", counts: countStatuses([refined, tooShort]) },
      { slug: "b", counts: countStatuses([refined]) },
    ]);
    expect(text).toBe(
      [
        "Refine statuses",
        "  a: refined 1, no_window 0, no_text 0, too_long 0, too_short 1, skipped chars 3",
        "  b: refined 1, no_window 0, no_text 0, too_long 0, too_short 0, skipped chars 2",
        "  Overall: refined 2, no_window 0, no_text 0, too_long 0, too_short 1, skipped chars 5",
        "",
      ].join("\n"),
    );
  });
});
