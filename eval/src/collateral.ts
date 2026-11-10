import { GROSS_ERROR_MS } from "./errors";
import type { TruthLine } from "./labels";
import { type Prediction, predictionsByLine } from "./metrics";
import type { Perturbation, PerturbationKind } from "./perturbations";

/** What one perturbation did to the lines it did not touch. */
export type Outcome = {
  /** Counted lines that were good in the baseline and are not good now. */
  collateral: number;
  /** The original 1-based numbers of those lines. */
  collateralLines: number[];
  /** Counted lines that were not good in the baseline and are good now. */
  improved: number;
};

/** A line is good when it has a start within `GROSS_ERROR_MS` of the truth. */
function isGood(
  prediction: Prediction | undefined,
  trueStart: number,
): boolean {
  if (prediction === undefined || prediction.start === null) return false;
  return Math.abs(prediction.start - trueStart) <= GROSS_ERROR_MS;
}

/**
 * Compares the perturbed run with the baseline over the labeled lines the edit
 * left comparable (`perturbation.lineMap`). `perturbed` is numbered like the
 * perturbed lyrics; `lineMap` takes each original line there.
 */
export function perturbationOutcome(
  truth: readonly TruthLine[],
  baseline: Prediction[],
  perturbation: Perturbation,
  perturbed: Prediction[],
): Outcome {
  const before = predictionsByLine(baseline);
  const after = predictionsByLine(perturbed);
  const collateralLines: number[] = [];
  let improved = 0;
  for (const { line, start } of truth) {
    const newLine = perturbation.lineMap.get(line);
    if (newLine === undefined) continue;
    const wasGood = isGood(before.get(line), start);
    const isNowGood = isGood(after.get(newLine), start);
    if (wasGood && !isNowGood) collateralLines.push(line);
    if (!wasGood && isNowGood) improved += 1;
  }
  return { collateral: collateralLines.length, collateralLines, improved };
}

/** The outcomes of every perturbation of one kind, over all songs. */
export type KindSummary = {
  kind: PerturbationKind;
  perturbations: number;
  /** Perturbations with at least one collateral line. */
  withCollateral: number;
  /** Perturbations with more than one collateral line. */
  overOne: number;
  /** `overOne` / `perturbations`: the adoption criterion for stage 2. */
  overOneRate: number | null;
  meanCollateral: number | null;
  maxCollateral: number | null;
  /** Lines that became good, summed. Context, not a criterion. */
  improved: number;
};

export function summarizeKind(
  kind: PerturbationKind,
  outcomes: readonly Outcome[],
): KindSummary {
  const total = outcomes.length;
  const overOne = outcomes.filter(({ collateral }) => collateral > 1).length;
  const sum = outcomes.reduce((acc, { collateral }) => acc + collateral, 0);
  return {
    kind,
    perturbations: total,
    withCollateral: outcomes.filter(({ collateral }) => collateral > 0).length,
    overOne,
    overOneRate: total === 0 ? null : overOne / total,
    meanCollateral: total === 0 ? null : sum / total,
    maxCollateral:
      total === 0 ? null : Math.max(...outcomes.map((o) => o.collateral)),
    improved: outcomes.reduce((acc, { improved: n }) => acc + n, 0),
  };
}
