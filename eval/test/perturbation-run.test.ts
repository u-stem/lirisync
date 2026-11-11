import { describe, expect, test } from "bun:test";
import {
  type AnchoredLine,
  type Anchorer,
  type AnchorRequest,
  parseMs,
  type RefinedLine,
  type RefineRequest,
  type Refiner,
} from "@lirisync/core";
import type { Prediction } from "../src/metrics";
import {
  buildPerturbationReport,
  formatPerturbationReport,
  type Predict,
  runSongPerturbations,
  type StagePredictions,
  stagePredictor,
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

/** Refines every line with a window to the start of that window plus 100 ms. */
class ShiftRefiner implements Refiner {
  readonly requests: RefineRequest[] = [];

  async refine(request: RefineRequest): Promise<RefinedLine[]> {
    this.requests.push(request);
    return request.windows.map(
      (window): RefinedLine =>
        window === null
          ? { status: "no_window", skippedChars: 0 }
          : {
              status: "refined",
              start: parseMs(window.start + 100),
              end: window.end,
              logRatio: 0,
              skippedChars: 0,
            },
    );
  }
}

const refineBase: Omit<RefineRequest, "lyrics" | "windows"> = {
  audioPath: "vocals.wav",
  modelDir: "model",
  spelling: "surface",
  ignored: [],
  margin: parseMs(1000),
};

const lyrics = ["a", "b", "b", "c"];
const truth = [1, 2, 3, 4].map((line) => ({
  line,
  start: parseMs(line * 5000),
}));
const baselinePredictions: Prediction[] = truth.map(({ line, start }) => ({
  line,
  start,
}));
const baseline: StagePredictions = {
  anchor: baselinePredictions,
  refine: null,
};
const refinedBaseline: StagePredictions = {
  anchor: baselinePredictions,
  refine: baselinePredictions,
};
const plan = perturbations(lyrics, truth);
const song = { slug: "demo", truth };

function refiningPredictor(): Predict {
  return stagePredictor(new SecondsAnchorer(), [], {
    refiner: new ShiftRefiner(),
    request: refineBase,
  });
}

describe("stagePredictor", () => {
  test("anchors the lyrics with the given words and no ignored characters", async () => {
    const anchorer = new SecondsAnchorer();
    await stagePredictor(anchorer, [], null)(lyrics);
    expect(anchorer.requests).toEqual([{ lyrics, words: [], ignored: [] }]);
  });

  test("gives the stage 1 predictions of the anchored lines", async () => {
    const predictions = await stagePredictor(
      new SecondsAnchorer(),
      [],
      null,
    )(lyrics);
    expect(predictions.anchor.map((p) => p.start)).toEqual(
      truth.map((t) => t.start),
    );
  });

  test("gives no stage 2 predictions without a refiner", async () => {
    const predictions = await stagePredictor(
      new SecondsAnchorer(),
      [],
      null,
    )(lyrics);
    expect(predictions.refine).toBeNull();
  });

  test("refines once, with the windows stage 1 found", async () => {
    const refiner = new ShiftRefiner();
    await stagePredictor(new SecondsAnchorer(), [], {
      refiner,
      request: refineBase,
    })(lyrics);
    expect(refiner.requests).toEqual([
      {
        ...refineBase,
        lyrics,
        windows: [1, 2, 3, 4].map((n) => ({
          start: parseMs(n * 5000),
          end: parseMs(n * 5000 + 500),
        })),
      },
    ]);
  });

  test("moves the window starts by the start shift", async () => {
    const refiner = new ShiftRefiner();
    await stagePredictor(new SecondsAnchorer(), [], {
      refiner,
      request: refineBase,
      startShiftMs: 200,
    })(lyrics);
    expect(refiner.requests[0]?.windows[0]).toEqual({
      start: parseMs(5200),
      end: parseMs(5500),
    });
  });

  test("shifts the stage 2 predictions by the offset", async () => {
    const predictions = await stagePredictor(new SecondsAnchorer(), [], {
      refiner: new ShiftRefiner(),
      request: refineBase,
      offsetMs: -100,
    })(lyrics);
    expect(predictions.refine?.map((p) => p.start)).toEqual(
      truth.map((t) => t.start),
    );
  });

  test("gives the stage 2 predictions of the refined lines", async () => {
    const predictions = await refiningPredictor()(lyrics);
    expect(predictions.refine?.map((p) => p.start)).toEqual(
      truth.map((t) => parseMs(t.start + 100)),
    );
  });
});

describe("runSongPerturbations", () => {
  const stageOne = stagePredictor(new SecondsAnchorer(), [], null);

  test("gives one stage 1 record per perturbation", async () => {
    const records = await runSongPerturbations(stageOne, song, baseline, plan);
    expect(records.anchor).toHaveLength(plan.length);
  });

  test("gives no stage 2 records when the baseline has no stage 2", async () => {
    const records = await runSongPerturbations(stageOne, song, baseline, plan);
    expect(records.refine).toBeNull();
  });

  test("predicts each perturbed lyrics", async () => {
    const seen: (readonly string[])[] = [];
    const predict: Predict = async (perturbed) => {
      seen.push(perturbed);
      return stageOne(perturbed);
    };
    await runSongPerturbations(predict, song, baseline, plan);
    expect(seen).toEqual(plan.map((p) => p.lyrics));
  });

  test("records the lines pushed off by a deletion", async () => {
    const records = await runSongPerturbations(stageOne, song, baseline, plan);
    // Deleting line 1 moves every later line five seconds early in this fake.
    const deleteFirst = records.anchor.find(
      (r) => r.kind === "delete" && r.at === 1,
    );
    expect(deleteFirst?.collateralLines).toEqual([2, 3, 4]);
  });

  test("gives one stage 2 record per perturbation when the baseline has stage 2", async () => {
    const records = await runSongPerturbations(
      refiningPredictor(),
      song,
      refinedBaseline,
      plan,
    );
    expect(records.refine).toHaveLength(plan.length);
  });

  test("records the lines pushed off by a deletion in stage 2", async () => {
    const records = await runSongPerturbations(
      refiningPredictor(),
      song,
      refinedBaseline,
      plan,
    );
    const deleteFirst = records.refine?.find(
      (r) => r.kind === "delete" && r.at === 1,
    );
    expect(deleteFirst?.collateralLines).toEqual([2, 3, 4]);
  });

  test("names the song and the edit when the prediction fails", async () => {
    const failing: Predict = async () => {
      throw new Error("boom");
    };
    const run = runSongPerturbations(failing, song, baseline, plan);
    await expect(run).rejects.toThrow("demo: delete at line 1: boom");
  });

  test("throws when the baseline has stage 2 and the prediction has none", async () => {
    const run = runSongPerturbations(stageOne, song, refinedBaseline, plan);
    await expect(run).rejects.toThrow(
      "demo: delete at line 1: no stage 2 predictions",
    );
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

  test("starts with the default title", () => {
    const report = buildPerturbationReport([
      { slug: "demo", perturbations: [] },
    ]);
    expect(formatPerturbationReport(report)).toStartWith(
      "Perturbation (collateral: a line good in the baseline that is no longer good)\n",
    );
  });

  test("starts with the given title", () => {
    const report = buildPerturbationReport([
      { slug: "demo", perturbations: [] },
    ]);
    expect(
      formatPerturbationReport(report, "Stage 2 perturbation"),
    ).toStartWith(
      "Stage 2 perturbation (collateral: a line good in the baseline that is no longer good)\n",
    );
  });
});
