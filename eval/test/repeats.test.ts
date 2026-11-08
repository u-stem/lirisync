import { describe, expect, test } from "bun:test";
import { parseMs } from "@lirisync/core";
import type { TruthLine } from "../src/labels";
import type { Prediction } from "../src/metrics";
import { confusion, repeatGroups } from "../src/repeats";

function truth(line: number, start: number): TruthLine {
  return { line, start: parseMs(start) };
}

function predicted(line: number, start: number | null): Prediction {
  return { line, start: start === null ? null : parseMs(start) };
}

describe("repeatGroups", () => {
  test("groups lines with the same text by 1-based line number", () => {
    const lyrics = "sora\numi\nsora\n";
    const result = repeatGroups(lyrics);
    expect(result).toEqual([[1, 3]]);
  });

  test("a line that appears once is not a group", () => {
    const lyrics = "sora\numi\n";
    const result = repeatGroups(lyrics);
    expect(result).toEqual([]);
  });

  test("blank lines are not grouped", () => {
    const lyrics = "a\n\nb\n\n";
    const result = repeatGroups(lyrics);
    expect(result).toEqual([]);
  });

  test("full-width and half-width forms are the same text", () => {
    const lyrics = "ＡＢＣ\r\nABC \r\n";
    const result = repeatGroups(lyrics);
    expect(result).toEqual([[1, 2]]);
  });
});

describe("confusion", () => {
  const groups = [[1, 3]];
  const labels = [truth(1, 10000), truth(2, 20000), truth(3, 30000)];

  test("a start nearest its own occurrence is not confused", () => {
    const run = {
      truth: labels,
      predictions: [predicted(1, 12000), predicted(3, 31000)],
      groups,
    };
    const result = confusion([run]);
    expect(result.confused).toBe(0);
  });

  test("a start nearer another occurrence is confused", () => {
    const run = {
      truth: labels,
      predictions: [predicted(1, 29000), predicted(3, 31000)],
      groups,
    };
    const result = confusion([run]);
    expect(result.confused).toBe(1);
  });

  test("an equal distance is not confused", () => {
    const run = {
      truth: labels,
      predictions: [predicted(1, 20000)],
      groups,
    };
    const result = confusion([run]);
    expect(result.confused).toBe(0);
  });

  test("unmatched and ungrouped lines are not considered", () => {
    const run = {
      truth: labels,
      predictions: [
        predicted(1, null),
        predicted(2, 20000),
        predicted(3, 30000),
      ],
      groups,
    };
    const result = confusion([run]);
    expect(result.considered).toBe(1);
  });

  test("a repeated line with no other labeled occurrence is not considered", () => {
    const run = {
      truth: [truth(1, 10000)],
      predictions: [predicted(1, 10000), predicted(3, 30000)],
      groups,
    };
    const result = confusion([run]);
    expect(result.considered).toBe(0);
  });

  test("the rate pools songs", () => {
    const confusedSong = {
      truth: labels,
      predictions: [predicted(1, 29000), predicted(3, 31000)],
      groups,
    };
    const cleanSong = {
      truth: labels,
      predictions: [predicted(1, 10000), predicted(3, 30000)],
      groups,
    };
    const result = confusion([confusedSong, cleanSong]);
    expect(result.rate).toBe(0.25);
  });

  test("the rate is null when no repeated line was considered", () => {
    const run = { truth: labels, predictions: [], groups };
    const result = confusion([run]);
    expect(result.rate).toBeNull();
  });
});
