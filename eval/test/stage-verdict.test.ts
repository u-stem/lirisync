import { describe, expect, test } from "bun:test";
import type { KindSummary } from "../src/collateral";
import type { ErrorProfile } from "../src/errors";
import type { PerturbationReport } from "../src/perturbation-run";
import { formatStageTwoVerdict, stageTwoVerdict } from "../src/stage-verdict";

function profile(overrides: Partial<ErrorProfile> = {}): ErrorProfile {
  return {
    medianSignedErrorMs: 0,
    p90StartErrorMs: 400,
    grossErrorRate: 0.1,
    silentErrorRate: 0.05,
    confidenceAuroc: null,
    confidenceSpread: null,
    ...overrides,
  };
}

function kind(overOne: number): KindSummary {
  return {
    kind: "delete",
    perturbations: 10,
    withCollateral: overOne,
    overOne,
    overOneRate: overOne / 10,
    meanCollateral: 0,
    maxCollateral: overOne > 0 ? 2 : 0,
    improved: 0,
  };
}

function perturbation(...overOnes: number[]): PerturbationReport {
  return { kinds: overOnes.map(kind), songs: [] };
}

const STAGE_ONE = profile();

describe("stageTwoVerdict", () => {
  test("adopts stage 2 when it is no worse on every criterion", () => {
    const verdict = stageTwoVerdict(STAGE_ONE, profile(), perturbation(0, 0));
    expect(verdict.outcome).toBe("adopt");
  });

  test("rejects stage 2 with a longer tail", () => {
    const stageTwo = profile({ p90StartErrorMs: 415 });
    const verdict = stageTwoVerdict(STAGE_ONE, stageTwo, perturbation(0));
    expect(verdict.outcome).toBe("reject");
  });

  test("rejects stage 2 with more gross errors", () => {
    const stageTwo = profile({ grossErrorRate: 0.2 });
    const verdict = stageTwoVerdict(STAGE_ONE, stageTwo, perturbation(0));
    expect(verdict.outcome).toBe("reject");
  });

  test("rejects stage 2 with more silent errors", () => {
    const stageTwo = profile({ silentErrorRate: 0.1 });
    const verdict = stageTwoVerdict(STAGE_ONE, stageTwo, perturbation(0));
    expect(verdict.outcome).toBe("reject");
  });

  test("rejects stage 2 when a perturbation hits more than one other line", () => {
    const verdict = stageTwoVerdict(STAGE_ONE, profile(), perturbation(0, 1));
    expect(verdict.outcome).toBe("reject");
  });

  test("leaves it undecided when stage 2 has no high-confidence line", () => {
    const stageTwo = profile({ silentErrorRate: null });
    const verdict = stageTwoVerdict(STAGE_ONE, stageTwo, perturbation(0));
    expect(verdict.outcome).toBe("undecided");
  });

  test("leaves it undecided without a perturbation run", () => {
    const verdict = stageTwoVerdict(STAGE_ONE, profile(), null);
    expect(verdict.outcome).toBe("undecided");
  });

  test("a failed criterion outweighs an unmeasured one", () => {
    const stageTwo = profile({ p90StartErrorMs: 415, silentErrorRate: null });
    const verdict = stageTwoVerdict(STAGE_ONE, stageTwo, null);
    expect(verdict.outcome).toBe("reject");
  });

  test("counts an equal value as a pass", () => {
    const verdict = stageTwoVerdict(STAGE_ONE, profile(), perturbation(0));
    expect(verdict.criteria.map((c) => c.status)).toEqual([
      "pass",
      "pass",
      "pass",
      "pass",
    ]);
  });
});

describe("formatStageTwoVerdict", () => {
  test("shows each criterion and the outcome", () => {
    const stageTwo = profile({ p90StartErrorMs: 288, silentErrorRate: null });
    const text = formatStageTwoVerdict(
      stageTwoVerdict(STAGE_ONE, stageTwo, perturbation(0)),
    );
    expect(text).toBe(
      [
        "Stage 2 adoption (stage 2 vs stage 1; the license and running without torch are checked by hand)",
        "  P90 start error: 288 ms vs 400 ms, pass",
        "  Gross error rate: 10.0% vs 10.0%, pass",
        "  Silent error rate: — vs 5.0%, unmeasured",
        "  Perturbations hitting more than one other line: 0, pass",
        "  Verdict: UNDECIDED (unmeasured: silent error rate)",
        "",
      ].join("\n"),
    );
  });
});
