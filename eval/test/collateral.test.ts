import { describe, expect, test } from "bun:test";
import { parseMs } from "@lirisync/core";
import {
  type Outcome,
  perturbationOutcome,
  summarizeKind,
} from "../src/collateral";
import type { TruthLine } from "../src/labels";
import type { Prediction } from "../src/metrics";
import type { Perturbation } from "../src/perturbations";

function truth(...starts: number[]): TruthLine[] {
  return starts.map((start, i) => ({ line: i + 1, start: parseMs(start) }));
}

function predictions(...starts: (number | null)[]): Prediction[] {
  return starts.map((start, i) => ({
    line: i + 1,
    start: start === null ? null : parseMs(start),
  }));
}

function perturbation(
  map: [number, number][],
  excluded: number[] = [],
): Perturbation {
  return {
    kind: "delete",
    at: 1,
    span: 1,
    lyrics: [],
    lineMap: new Map(map),
    excluded,
  };
}

const labels = truth(1000, 2000, 3000);
const baseline = predictions(1000, 2000, 3000);

describe("perturbationOutcome", () => {
  test("a line that stays good is not collateral", () => {
    const result = perturbationOutcome(
      labels,
      baseline,
      perturbation([[1, 1]]),
      predictions(1500),
    );
    expect(result.collateral).toBe(0);
  });

  test("a good line moved by more than a second is collateral", () => {
    const result = perturbationOutcome(
      labels,
      baseline,
      perturbation([[1, 1]]),
      predictions(2001),
    );
    expect(result.collateralLines).toEqual([1]);
  });

  test("a line exactly a second off is still good", () => {
    const result = perturbationOutcome(
      labels,
      baseline,
      perturbation([[1, 1]]),
      predictions(2000),
    );
    expect(result.collateral).toBe(0);
  });

  test("a good line that loses its start is collateral", () => {
    const result = perturbationOutcome(
      labels,
      baseline,
      perturbation([[1, 1]]),
      predictions(null),
    );
    expect(result.collateral).toBe(1);
  });

  test("a line missing from the perturbed output is collateral", () => {
    const result = perturbationOutcome(
      labels,
      baseline,
      perturbation([[2, 5]]),
      predictions(1000),
    );
    expect(result.collateral).toBe(1);
  });

  test("reads the perturbed prediction at the mapped line", () => {
    const result = perturbationOutcome(
      labels,
      baseline,
      perturbation([[3, 2]]),
      predictions(9000, 3000),
    );
    expect(result.collateral).toBe(0);
  });

  test("a line that was already bad is not collateral", () => {
    const result = perturbationOutcome(
      labels,
      predictions(9000, 2000, 3000),
      perturbation([[1, 1]]),
      predictions(8000),
    );
    expect(result.collateral).toBe(0);
  });

  test("an excluded line is not counted", () => {
    const result = perturbationOutcome(
      labels,
      baseline,
      perturbation([], [1]),
      predictions(),
    );
    expect(result.collateral).toBe(0);
  });

  test("a bad line that becomes good is improved", () => {
    const result = perturbationOutcome(
      labels,
      predictions(9000, 2000, 3000),
      perturbation([[1, 1]]),
      predictions(1200),
    );
    expect(result.improved).toBe(1);
  });

  test("a line that stays good is not improved", () => {
    const result = perturbationOutcome(
      labels,
      baseline,
      perturbation([[1, 1]]),
      predictions(1200),
    );
    expect(result.improved).toBe(0);
  });
});

function outcome(collateral: number, improved = 0): Outcome {
  return {
    collateral,
    collateralLines: Array.from({ length: collateral }, (_, i) => i + 1),
    improved,
  };
}

describe("summarizeKind", () => {
  test("counts the perturbations", () => {
    const result = summarizeKind("delete", [outcome(0), outcome(2)]);
    expect(result.perturbations).toBe(2);
  });

  test("counts those with collateral", () => {
    const result = summarizeKind("delete", [
      outcome(0),
      outcome(1),
      outcome(2),
    ]);
    expect(result.withCollateral).toBe(2);
  });

  test("counts those with more than one collateral line", () => {
    const result = summarizeKind("delete", [
      outcome(0),
      outcome(1),
      outcome(2),
    ]);
    expect(result.overOne).toBe(1);
  });

  test("gives the share with more than one collateral line", () => {
    const result = summarizeKind("delete", [
      outcome(0),
      outcome(1),
      outcome(2),
    ]);
    expect(result.overOneRate).toBeCloseTo(1 / 3);
  });

  test("gives the mean collateral", () => {
    const result = summarizeKind("delete", [
      outcome(0),
      outcome(1),
      outcome(2),
    ]);
    expect(result.meanCollateral).toBe(1);
  });

  test("gives the maximum collateral", () => {
    const result = summarizeKind("delete", [
      outcome(0),
      outcome(1),
      outcome(3),
    ]);
    expect(result.maxCollateral).toBe(3);
  });

  test("sums the improved lines", () => {
    const result = summarizeKind("delete", [outcome(0, 2), outcome(1, 3)]);
    expect(result.improved).toBe(5);
  });

  test("has null rates without perturbations", () => {
    const result = summarizeKind("collapse", []);
    expect([
      result.perturbations,
      result.overOneRate,
      result.meanCollateral,
      result.maxCollateral,
    ]).toEqual([0, null, null, null]);
  });
});
