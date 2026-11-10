import { describe, expect, test } from "bun:test";
import { parseMs } from "@lirisync/core";
import type { TruthLine } from "../src/labels";
import { type Perturbation, perturbations } from "../src/perturbations";

function labels(...lines: number[]): TruthLine[] {
  return lines.map((line) => ({ line, start: parseMs(line * 1000) }));
}

function ofKind(
  all: Perturbation[],
  kind: Perturbation["kind"],
): Perturbation[] {
  return all.filter((p) => p.kind === kind);
}

function mapped(p: Perturbation): [number, number][] {
  return [...p.lineMap.entries()].sort((a, b) => a[0] - b[0]);
}

describe("perturbations: delete", () => {
  const lyrics = ["a", "b", "c", "d"];

  test("yields one perturbation per labeled line", () => {
    const result = ofKind(perturbations(lyrics, labels(1, 3)), "delete");
    expect(result.map((p) => p.at)).toEqual([1, 3]);
  });

  test("removes the line from the lyrics", () => {
    const [result] = ofKind(perturbations(lyrics, labels(2)), "delete");
    expect(result?.lyrics).toEqual(["a", "c", "d"]);
  });

  test("excludes the removed line", () => {
    const [result] = ofKind(perturbations(lyrics, labels(2, 3)), "delete");
    expect(result?.excluded).toEqual([2]);
  });

  test("shifts the later labeled lines up by one", () => {
    const [result] = ofKind(perturbations(lyrics, labels(1, 2, 4)), "delete");
    expect(result === undefined ? [] : mapped(result)).toEqual([
      [2, 1],
      [4, 3],
    ]);
  });

  test("does not delete the only line", () => {
    const result = ofKind(perturbations(["a"], labels(1)), "delete");
    expect(result).toEqual([]);
  });
});

describe("perturbations: duplicate", () => {
  const lyrics = ["a", "b", "c"];

  test("inserts a copy right after the line", () => {
    const [result] = ofKind(perturbations(lyrics, labels(2)), "duplicate");
    expect(result?.lyrics).toEqual(["a", "b", "b", "c"]);
  });

  test("excludes the duplicated line", () => {
    const [result] = ofKind(perturbations(lyrics, labels(2)), "duplicate");
    expect(result?.excluded).toEqual([2]);
  });

  test("shifts the later labeled lines down by one", () => {
    const [result] = ofKind(
      perturbations(lyrics, labels(1, 2, 3)),
      "duplicate",
    );
    expect(result === undefined ? [] : mapped(result)).toEqual([
      [2, 3],
      [3, 4],
    ]);
  });

  test("keeps the earlier labeled lines in place", () => {
    const all = ofKind(perturbations(lyrics, labels(1, 2, 3)), "duplicate");
    expect(all[1] === undefined ? [] : mapped(all[1])).toEqual([
      [1, 1],
      [3, 4],
    ]);
  });
});

describe("perturbations: collapse", () => {
  test("removes the second copy of an immediately repeated line", () => {
    const lyrics = ["a", "b", "b", "c"];
    const [result] = ofKind(
      perturbations(lyrics, labels(1, 2, 3, 4)),
      "collapse",
    );
    expect(result?.lyrics).toEqual(["a", "b", "c"]);
  });

  test("excludes both copies", () => {
    const lyrics = ["a", "b", "b", "c"];
    const [result] = ofKind(
      perturbations(lyrics, labels(1, 2, 3, 4)),
      "collapse",
    );
    expect(result?.excluded).toEqual([2, 3]);
  });

  test("shifts the later lines up by the block length", () => {
    const lyrics = ["a", "b", "c", "b", "c", "d"];
    const result = ofKind(perturbations(lyrics, labels(1, 6)), "collapse");
    expect(result[0] === undefined ? [] : mapped(result[0])).toEqual([
      [1, 1],
      [6, 4],
    ]);
  });

  test("reports where the repeated block starts", () => {
    const lyrics = ["a", "b", "c", "b", "c", "d"];
    const result = ofKind(perturbations(lyrics, labels(1)), "collapse");
    expect(result.map((p) => [p.at, p.span])).toEqual([[2, 2]]);
  });

  test("keeps a shorter and a longer block at the same place", () => {
    const lyrics = ["a", "b", "a", "b", "a", "b", "a", "b"];
    const result = ofKind(perturbations(lyrics, labels(1)), "collapse");
    expect(result.filter((p) => p.at === 1).map((p) => p.span)).toEqual([2, 4]);
  });

  test("compares after NFKC and trimming", () => {
    const lyrics = ["ＡＢＣ", "x", "ABC ", "x"];
    const result = ofKind(perturbations(lyrics, labels(1)), "collapse");
    expect(result.map((p) => [p.at, p.span])).toEqual([[1, 2]]);
  });

  test("skips a block of blank lines", () => {
    const lyrics = ["a", "", "", "b"];
    const result = ofKind(perturbations(lyrics, labels(1)), "collapse");
    expect(result).toEqual([]);
  });

  test("yields nothing without a repeated block", () => {
    const result = ofKind(
      perturbations(["a", "b", "c"], labels(1)),
      "collapse",
    );
    expect(result).toEqual([]);
  });

  test("does not look at blocks longer than four lines", () => {
    const lyrics = ["a", "b", "c", "d", "e", "a", "b", "c", "d", "e"];
    const result = ofKind(perturbations(lyrics, labels(1)), "collapse");
    expect(result).toEqual([]);
  });

  test("leaves unlabeled lines out of the exclusions", () => {
    const lyrics = ["a", "b", "b", "c"];
    const [result] = ofKind(perturbations(lyrics, labels(1, 3)), "collapse");
    expect(result?.excluded).toEqual([3]);
  });
});
