import type { Ms } from "@lirisync/core";
import type { TruthLine } from "./labels";

/** The aligner's answer for one lyric line. `null` means unmatched. */
export type Prediction = { line: number; start: Ms | null };

export type SongRun = { truth: TruthLine[]; predictions: Prediction[] };

export type Score = {
  labeled: number;
  matched: number;
  matchRate: number;
  /** Median of |predicted - true| line start over matched lines. */
  medianStartErrorMs: number | null;
};

/** Accuracy gate that ends the validation phase. */
export const MAX_MEDIAN_START_ERROR_MS = 500;
export const MIN_MATCH_RATE = 0.85;

function median(values: number[]): number | null {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  const upper = sorted[middle];
  if (upper === undefined) return null;
  if (sorted.length % 2 === 1) return upper;
  const lower = sorted[middle - 1] ?? upper;
  return (lower + upper) / 2;
}

/**
 * Indexes predictions by line number. Throws on a duplicate line: keeping the
 * last one would hide an aligner bug inside the metrics, and labels are held
 * to the same rule.
 */
export function predictionsByLine(
  predictions: Prediction[],
): Map<number, Ms | null> {
  const byLine = new Map<number, Ms | null>();
  for (const { line, start } of predictions) {
    if (byLine.has(line)) {
      throw new Error(`Prediction for line ${line} is predicted twice`);
    }
    byLine.set(line, start);
  }
  return byLine;
}

/**
 * Scores the labeled lines of every song together. Lines are pooled before
 * the median so that a short song does not weigh as much as a long one.
 * Predictions for lines without a label are ignored.
 */
export function score(runs: SongRun[]): Score {
  let labeled = 0;
  const errors: number[] = [];
  for (const { truth, predictions } of runs) {
    const startOf = predictionsByLine(predictions);
    for (const { line, start } of truth) {
      labeled += 1;
      const predictedStart = startOf.get(line);
      if (predictedStart === undefined || predictedStart === null) continue;
      errors.push(Math.abs(predictedStart - start));
    }
  }
  if (labeled === 0) {
    throw new Error("The evaluation set has no labeled lines");
  }
  return {
    labeled,
    matched: errors.length,
    matchRate: errors.length / labeled,
    medianStartErrorMs: median(errors),
  };
}

export function passesAccuracyGate(result: Score): boolean {
  return (
    result.medianStartErrorMs !== null &&
    result.medianStartErrorMs <= MAX_MEDIAN_START_ERROR_MS &&
    result.matchRate >= MIN_MATCH_RATE
  );
}
