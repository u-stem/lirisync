import type { TruthLine } from "./labels";
import { type Prediction, predictionsByLine } from "./metrics";

/**
 * Line numbers (1-based) of lyric lines whose text appears more than once,
 * one group per distinct text. Text is compared after NFKC and trimming so
 * that width variants of the same line group together; anything finer is the
 * aligner's job, not the evaluator's.
 */
export function repeatGroups(lyrics: string): number[][] {
  const linesByText = new Map<string, number[]>();
  lyrics.split(/\r?\n/).forEach((raw, index) => {
    const text = raw.normalize("NFKC").trim();
    if (text === "") return;
    const lines = linesByText.get(text) ?? [];
    lines.push(index + 1);
    linesByText.set(text, lines);
  });
  return [...linesByText.values()].filter((lines) => lines.length > 1);
}

export type RepeatRun = {
  truth: TruthLine[];
  predictions: Prediction[];
  groups: number[][];
};

export type Confusion = {
  considered: number;
  confused: number;
  rate: number | null;
};

/**
 * How often a repeated line is placed at another occurrence of the same text
 * (e.g. the second chorus aligned onto the third). A line counts as confused
 * when its predicted start is strictly closer to another labeled occurrence's
 * true start than to its own. Only matched, labeled lines with at least one
 * other labeled occurrence are considered; counting the rest would dilute the
 * rate with lines that cannot be confused.
 */
export function confusion(runs: RepeatRun[]): Confusion {
  let considered = 0;
  let confused = 0;
  for (const { truth, predictions, groups } of runs) {
    const trueStart = new Map(truth.map((t) => [t.line, t.start]));
    const byLine = predictionsByLine(predictions);
    for (const group of groups) {
      for (const line of group) {
        const own = trueStart.get(line);
        const guess = byLine.get(line)?.start;
        if (own === undefined || guess === undefined || guess === null) {
          continue;
        }
        const others = group
          .filter((other) => other !== line)
          .flatMap((other) => {
            const start = trueStart.get(other);
            return start === undefined ? [] : [start];
          });
        if (others.length === 0) continue;
        considered += 1;
        const ownDistance = Math.abs(guess - own);
        if (others.some((start) => Math.abs(guess - start) < ownDistance)) {
          confused += 1;
        }
      }
    }
  }
  return {
    considered,
    confused,
    rate: considered === 0 ? null : confused / considered,
  };
}
