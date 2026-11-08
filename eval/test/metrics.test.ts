import { describe, expect, test } from "bun:test";
import { parseMs } from "@lirisync/core";
import type { TruthLine } from "../src/labels";
import {
  type Prediction,
  passesAccuracyGate,
  type Score,
  score,
} from "../src/metrics";

function truth(line: number, start: number): TruthLine {
  return { line, start: parseMs(start) };
}

function predicted(line: number, start: number | null): Prediction {
  return { line, start: start === null ? null : parseMs(start) };
}

describe("score", () => {
  test("match rate is the share of labeled lines that got a start time", () => {
    const run = {
      truth: [truth(1, 1000), truth(2, 2000), truth(3, 3000), truth(4, 4000)],
      predictions: [
        predicted(1, 1000),
        predicted(2, null),
        predicted(3, 3000),
        predicted(4, 4000),
      ],
    };
    const result = score([run]);
    expect(result.matchRate).toBe(0.75);
  });

  test("a labeled line missing from the predictions counts as unmatched", () => {
    const run = {
      truth: [truth(1, 1000), truth(2, 2000)],
      predictions: [predicted(1, 1000)],
    };
    const result = score([run]);
    expect(result.matched).toBe(1);
  });

  test("predictions for unlabeled lines are ignored", () => {
    const run = {
      truth: [truth(1, 1000)],
      predictions: [predicted(1, 1000), predicted(2, 2000)],
    };
    const result = score([run]);
    expect(result.labeled).toBe(1);
  });

  test("the start error is absolute", () => {
    const run = {
      truth: [truth(1, 5000)],
      predictions: [predicted(1, 4600)],
    };
    const result = score([run]);
    expect(result.medianStartErrorMs).toBe(400);
  });

  test("the median of an odd count is the middle error", () => {
    const run = {
      truth: [truth(1, 1000), truth(2, 2000), truth(3, 3000)],
      predictions: [predicted(1, 1100), predicted(2, 2900), predicted(3, 3300)],
    };
    const result = score([run]);
    expect(result.medianStartErrorMs).toBe(300);
  });

  test("the median of an even count averages the middle two", () => {
    const run = {
      truth: [truth(1, 1000), truth(2, 2000)],
      predictions: [predicted(1, 1100), predicted(2, 2401)],
    };
    const result = score([run]);
    expect(result.medianStartErrorMs).toBe(250.5);
  });

  test("the median is null when no line matched", () => {
    const run = {
      truth: [truth(1, 1000)],
      predictions: [predicted(1, null)],
    };
    const result = score([run]);
    expect(result.medianStartErrorMs).toBeNull();
  });

  test("lines are pooled across songs before taking the median", () => {
    const songA = {
      truth: [truth(1, 1000)],
      predictions: [predicted(1, 1100)],
    };
    const songB = {
      truth: [truth(1, 1000), truth(2, 2000)],
      predictions: [predicted(1, 1700), predicted(2, 2900)],
    };
    const result = score([songA, songB]);
    expect(result.medianStartErrorMs).toBe(700);
  });

  test("two predictions for the same line are an error", () => {
    const run = {
      truth: [truth(1, 1000)],
      predictions: [predicted(1, 1000), predicted(1, 5000)],
    };
    expect(() => score([run])).toThrow("line 1 is predicted twice");
  });

  test("an evaluation set without labeled lines is an error", () => {
    const run = { truth: [], predictions: [predicted(1, 1000)] };
    expect(() => score([run])).toThrow("no labeled lines");
  });
});

describe("passesAccuracyGate", () => {
  function scoreOf(matchRate: number, median: number | null): Score {
    return {
      labeled: 100,
      matched: Math.round(matchRate * 100),
      matchRate,
      medianStartErrorMs: median,
    };
  }

  test("passes exactly at 500 ms and 85 %", () => {
    const result = passesAccuracyGate(scoreOf(0.85, 500));
    expect(result).toBe(true);
  });

  test("fails above 500 ms", () => {
    const result = passesAccuracyGate(scoreOf(0.9, 500.5));
    expect(result).toBe(false);
  });

  test("fails below 85 %", () => {
    const result = passesAccuracyGate(scoreOf(0.84, 100));
    expect(result).toBe(false);
  });

  test("fails when nothing matched", () => {
    const result = passesAccuracyGate(scoreOf(0, null));
    expect(result).toBe(false);
  });
});
