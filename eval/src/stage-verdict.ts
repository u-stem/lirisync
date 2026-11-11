import type { ErrorProfile } from "./errors";
import type { PerturbationReport } from "./perturbation-run";

export type CriterionStatus = "pass" | "fail" | "unmeasured";

export type Criterion = {
  name: string;
  /** Stage 2's value. */
  stageTwo: number | null;
  /** Stage 1's value; null for a criterion stage 2 meets on its own. */
  stageOne: number | null;
  unit: "ms" | "rate" | "count";
  status: CriterionStatus;
};

export type StageTwoVerdict = {
  criteria: Criterion[];
  /**
   * `adopt` when every criterion passes, `reject` when one fails, `undecided`
   * when none fails but one could not be measured.
   */
  outcome: "adopt" | "reject" | "undecided";
};

/** Stage 2 must be no worse than stage 1. */
function noWorse(
  name: string,
  unit: Criterion["unit"],
  stageTwo: number | null,
  stageOne: number | null,
): Criterion {
  const status: CriterionStatus =
    stageTwo === null || stageOne === null
      ? "unmeasured"
      : stageTwo <= stageOne
        ? "pass"
        : "fail";
  return { name, stageTwo, stageOne, unit, status };
}

/**
 * The adoption criteria for stage 2 of the evaluation plan: its P90, gross
 * error rate and silent error rate no worse than stage 1's, and no
 * perturbation hitting more than one other line. The license and running
 * without torch are checked by hand, not here.
 *
 * A silent error rate is unmeasured when no line reaches the high-confidence
 * threshold, and the perturbation criterion without a perturbation run.
 */
export function stageTwoVerdict(
  stageOne: ErrorProfile,
  stageTwo: ErrorProfile,
  stageTwoPerturbation: PerturbationReport | null,
): StageTwoVerdict {
  const overOne =
    stageTwoPerturbation === null
      ? null
      : stageTwoPerturbation.kinds.reduce((sum, kind) => sum + kind.overOne, 0);
  const criteria: Criterion[] = [
    noWorse(
      "P90 start error",
      "ms",
      stageTwo.p90StartErrorMs,
      stageOne.p90StartErrorMs,
    ),
    noWorse(
      "Gross error rate",
      "rate",
      stageTwo.grossErrorRate,
      stageOne.grossErrorRate,
    ),
    noWorse(
      "Silent error rate",
      "rate",
      stageTwo.silentErrorRate,
      stageOne.silentErrorRate,
    ),
    {
      name: "Perturbations hitting more than one other line",
      stageTwo: overOne,
      stageOne: null,
      unit: "count",
      status: overOne === null ? "unmeasured" : overOne === 0 ? "pass" : "fail",
    },
  ];
  const statuses = criteria.map((criterion) => criterion.status);
  const outcome = statuses.includes("fail")
    ? "reject"
    : statuses.includes("unmeasured")
      ? "undecided"
      : "adopt";
  return { criteria, outcome };
}

const MISSING = "—";

function value(number: number | null, unit: Criterion["unit"]): string {
  if (number === null) return MISSING;
  if (unit === "ms") return `${Math.round(number)} ms`;
  if (unit === "rate") return `${(number * 100).toFixed(1)}%`;
  return String(number);
}

/** The verdict as a report block, one line per criterion. */
export function formatStageTwoVerdict(verdict: StageTwoVerdict): string {
  const lines = [
    "Stage 2 adoption (stage 2 vs stage 1; the license and running without torch are checked by hand)",
  ];
  for (const criterion of verdict.criteria) {
    const shown =
      criterion.unit === "count"
        ? value(criterion.stageTwo, criterion.unit)
        : `${value(criterion.stageTwo, criterion.unit)} vs ${value(criterion.stageOne, criterion.unit)}`;
    lines.push(`  ${criterion.name}: ${shown}, ${criterion.status}`);
  }
  const unmeasured = verdict.criteria
    .filter((criterion) => criterion.status === "unmeasured")
    .map((criterion) => criterion.name.toLowerCase());
  const outcome = verdict.outcome.toUpperCase();
  lines.push(
    verdict.outcome === "undecided"
      ? `  Verdict: ${outcome} (unmeasured: ${unmeasured.join(", ")})`
      : `  Verdict: ${outcome}`,
  );
  return `${lines.join("\n")}\n`;
}
