import { describe, expect, test } from "bun:test";
import {
  type AnchoredLine,
  type Anchorer,
  type AnchorRequest,
  parseMs,
} from "@lirisync/core";
import type { Prediction } from "../src/metrics";
import {
  buildPerturbationReport,
  formatPerturbationReport,
  runSongPerturbations,
} from "../src/perturbation-run";
import { perturbations } from "../src/perturbations";

/** Places line n (1-based) of whatever it is given at 5n seconds. */
class SecondsAnchorer implements Anchorer {
  readonly requests: AnchorRequest[] = [];

  async anchor(request: AnchorRequest): Promise<AnchoredLine[]> {
    this.requests.push(request);
    return request.lyrics.map(
      (_, index): AnchoredLine => ({
        status: "anchor",
        start: parseMs((index + 1) * 5000),
        end: parseMs((index + 1) * 5000 + 500),
        matchRatio: 1,
        ambiguous: false,
      }),
    );
  }
}

const lyrics = ["a", "b", "b", "c"];
const truth = [1, 2, 3, 4].map((line) => ({
  line,
  start: parseMs(line * 5000),
}));
const baseline: Prediction[] = truth.map(({ line, start }) => ({
  line,
  start,
}));
const plan = perturbations(lyrics, truth);

describe("runSongPerturbations", () => {
  test("gives one record per perturbation", async () => {
    const records = await runSongPerturbations(
      new SecondsAnchorer(),
      { slug: "demo", words: [], truth },
      baseline,
      plan,
    );
    expect(records).toHaveLength(plan.length);
  });

  test("anchors each perturbed lyrics with no ignored characters", async () => {
    const anchorer = new SecondsAnchorer();
    await runSongPerturbations(
      anchorer,
      { slug: "demo", words: [], truth },
      baseline,
      plan,
    );
    expect(anchorer.requests.map((r) => r.ignored.length)).toEqual(
      plan.map(() => 0),
    );
  });

  test("sends the perturbed lyrics", async () => {
    const anchorer = new SecondsAnchorer();
    await runSongPerturbations(
      anchorer,
      { slug: "demo", words: [], truth },
      baseline,
      plan,
    );
    expect(anchorer.requests[0]?.lyrics).toEqual(plan[0]?.lyrics);
  });

  test("records the lines pushed off by a deletion", async () => {
    const records = await runSongPerturbations(
      new SecondsAnchorer(),
      { slug: "demo", words: [], truth },
      baseline,
      plan,
    );
    // Deleting line 1 moves every later line five seconds early in this fake.
    const deleteFirst = records.find((r) => r.kind === "delete" && r.at === 1);
    expect(deleteFirst?.collateralLines).toEqual([2, 3, 4]);
  });

  test("names the song and the edit when the anchorer fails", async () => {
    const failing: Anchorer = {
      anchor: async () => {
        throw new Error("boom");
      },
    };
    const run = runSongPerturbations(
      failing,
      { slug: "demo", words: [], truth },
      baseline,
      plan,
    );
    await expect(run).rejects.toThrow("demo: delete at line 1: boom");
  });
});

describe("buildPerturbationReport", () => {
  const record = {
    kind: "delete" as const,
    at: 1,
    span: 1,
    collateral: 2,
    collateralLines: [2, 3],
    improved: 0,
  };

  test("summarizes every kind, in a fixed order", () => {
    const report = buildPerturbationReport([
      { slug: "demo", perturbations: [record] },
    ]);
    expect(report.kinds.map((k) => k.kind)).toEqual([
      "delete",
      "duplicate",
      "collapse",
    ]);
  });

  test("pools the songs in a kind", () => {
    const report = buildPerturbationReport([
      { slug: "one", perturbations: [record] },
      { slug: "two", perturbations: [record, record] },
    ]);
    expect(report.kinds[0]?.perturbations).toBe(3);
  });

  test("keeps the records of each song", () => {
    const report = buildPerturbationReport([
      { slug: "demo", perturbations: [record] },
    ]);
    expect(report.songs).toEqual([{ slug: "demo", perturbations: [record] }]);
  });
});

describe("formatPerturbationReport", () => {
  test("shows a kind without perturbations as a dash", () => {
    const report = buildPerturbationReport([
      { slug: "demo", perturbations: [] },
    ]);
    expect(formatPerturbationReport(report)).toContain(
      "collapse: 0 perturbations, over one —",
    );
  });

  test("shows the share of perturbations with more than one collateral line", () => {
    const report = buildPerturbationReport([
      {
        slug: "demo",
        perturbations: [
          {
            kind: "delete",
            at: 1,
            span: 1,
            collateral: 2,
            collateralLines: [2, 3],
            improved: 0,
          },
          {
            kind: "delete",
            at: 2,
            span: 1,
            collateral: 0,
            collateralLines: [],
            improved: 1,
          },
        ],
      },
    ]);
    expect(formatPerturbationReport(report)).toContain(
      "delete: 2 perturbations, over one 50.0% (1/2)",
    );
  });
});
