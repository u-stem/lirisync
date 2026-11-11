import { describe, expect, test } from "bun:test";
import { parseMs } from "@lirisync/core";
import { errorProfile } from "../src/errors";
import type { TruthLine } from "../src/labels";
import type { Prediction, SongRun } from "../src/metrics";

function truth(line: number, start: number): TruthLine {
  return { line, start: parseMs(start) };
}

function predicted(
  line: number,
  start: number | null,
  confidence?: number,
): Prediction {
  const at = start === null ? null : parseMs(start);
  return confidence === undefined
    ? { line, start: at }
    : { line, start: at, confidence };
}

/** One song whose line k is labeled at k seconds and predicted `errors[k-1]` ms late. */
function runWithErrors(errors: number[], confidences?: number[]): SongRun {
  return {
    truth: errors.map((_, k) => truth(k + 1, (k + 1) * 1000)),
    predictions: errors.map((error, k) =>
      predicted(k + 1, (k + 1) * 1000 + error, confidences?.[k]),
    ),
  };
}

describe("errorProfile", () => {
  test("spreads the confidence of the matched lines", () => {
    const run = runWithErrors([0, 0, 0], [0.2, 0.9, 0.5]);
    const result = errorProfile([run], { highConfidence: 0.8 });
    expect(result.confidenceSpread).toEqual({
      min: 0.2,
      median: 0.5,
      max: 0.9,
      high: 1,
      lines: 3,
    });
  });

  test("has no confidence spread when the aligner reports none", () => {
    const result = errorProfile([runWithErrors([0, 0])]);
    expect(result.confidenceSpread).toBeNull();
  });

  test("the bias is the median of predicted minus true", () => {
    const result = errorProfile([runWithErrors([-300, -100, 50])]);
    expect(result.medianSignedErrorMs).toBe(-100);
  });

  test("the bias is positive when the predictions are late", () => {
    const result = errorProfile([runWithErrors([100, 200, 300, 400])]);
    expect(result.medianSignedErrorMs).toBe(250);
  });

  test("the bias is null when no line matched", () => {
    const run = { truth: [truth(1, 1000)], predictions: [predicted(1, null)] };
    const result = errorProfile([run]);
    expect(result.medianSignedErrorMs).toBeNull();
  });

  test("P90 is the nearest-rank 90th percentile of the start errors", () => {
    const errors = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100];
    const result = errorProfile([runWithErrors(errors)]);
    expect(result.p90StartErrorMs).toBe(90);
  });

  test("P90 rounds the rank up", () => {
    const result = errorProfile([runWithErrors([10, 20, 30])]);
    expect(result.p90StartErrorMs).toBe(30);
  });

  test("P90 is null when no line matched", () => {
    const run = { truth: [truth(1, 1000)], predictions: [predicted(1, null)] };
    const result = errorProfile([run]);
    expect(result.p90StartErrorMs).toBeNull();
  });

  test("the gross error rate counts matched lines off by more than one second", () => {
    const result = errorProfile([runWithErrors([0, 1000, 1001, 5000])]);
    expect(result.grossErrorRate).toBe(0.5);
  });

  test("unmatched lines are not counted in the gross error rate", () => {
    const run = {
      truth: [truth(1, 1000), truth(2, 2000)],
      predictions: [predicted(1, 3000), predicted(2, null)],
    };
    const result = errorProfile([run]);
    expect(result.grossErrorRate).toBe(1);
  });

  test("the silent error rate is the share of high-confidence lines that are gross errors", () => {
    const run = runWithErrors([0, 2000, 2000, 0], [0.9, 0.9, 0.1, 0.1]);
    const result = errorProfile([run], { highConfidence: 0.8 });
    expect(result.silentErrorRate).toBe(0.5);
  });

  test("a line exactly at the threshold counts as high confidence", () => {
    const run = runWithErrors([2000], [0.8]);
    const result = errorProfile([run], { highConfidence: 0.8 });
    expect(result.silentErrorRate).toBe(1);
  });

  test("the silent error rate is null when no line is high confidence", () => {
    const run = runWithErrors([2000], [0.1]);
    const result = errorProfile([run], { highConfidence: 0.8 });
    expect(result.silentErrorRate).toBeNull();
  });

  test("AUROC is 1 when every correct line is more confident than every gross error", () => {
    const run = runWithErrors([0, 0, 2000, 2000], [0.9, 0.7, 0.6, 0.1]);
    const result = errorProfile([run]);
    expect(result.confidenceAuroc).toBe(1);
  });

  test("AUROC is 0 when the confidence is inverted", () => {
    const run = runWithErrors([0, 2000], [0.1, 0.9]);
    const result = errorProfile([run]);
    expect(result.confidenceAuroc).toBe(0);
  });

  test("AUROC counts a tie between a correct line and a gross error as half", () => {
    const run = runWithErrors([0, 0, 2000], [0.9, 0.5, 0.5]);
    const result = errorProfile([run]);
    expect(result.confidenceAuroc).toBe(0.75);
  });

  test("AUROC is null without both correct lines and gross errors", () => {
    const run = runWithErrors([0, 0], [0.9, 0.5]);
    const result = errorProfile([run]);
    expect(result.confidenceAuroc).toBeNull();
  });

  test("AUROC is null for an aligner that reports no confidence", () => {
    const result = errorProfile([runWithErrors([0, 2000])]);
    expect(result.confidenceAuroc).toBeNull();
  });

  test("the silent error rate is null for an aligner that reports no confidence", () => {
    const result = errorProfile([runWithErrors([0, 2000])]);
    expect(result.silentErrorRate).toBeNull();
  });

  test("lines are pooled across songs, not averaged per song", () => {
    const result = errorProfile([
      runWithErrors([2000]),
      runWithErrors([0, 0, 0]),
    ]);
    expect(result.grossErrorRate).toBe(0.25);
  });

  test("a matched line without a confidence among lines with one is an error", () => {
    const run = {
      truth: [truth(1, 1000), truth(2, 2000)],
      predictions: [predicted(1, 1000, 0.9), predicted(2, 2000)],
    };
    expect(() => errorProfile([runWithErrors([0], [0.9]), run])).toThrow(
      "song 2, line 2 has no confidence",
    );
  });

  test.each([-0.1, 1.1, Number.NaN])(
    "a confidence of %p is an error",
    (confidence) => {
      const run = runWithErrors([0], [confidence]);
      expect(() => errorProfile([run])).toThrow("outside 0 to 1");
    },
  );
});
