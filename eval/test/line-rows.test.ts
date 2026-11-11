import { describe, expect, test } from "bun:test";
import { parseMs } from "@lirisync/core";
import { lineRows } from "../src/line-rows";
import type { SongResult } from "../src/report";

function song(
  slug: string,
  truth: [number, number][],
  predictions: [number, number | null, number?][],
): SongResult {
  return {
    slug,
    lyricsText: "",
    truth: truth.map(([line, ms]) => ({ line, start: parseMs(ms) })),
    predictions: predictions.map(([line, ms, confidence]) => ({
      line,
      start: ms === null ? null : parseMs(ms),
      ...(confidence === undefined ? {} : { confidence }),
    })),
  };
}

const stageOne = [
  song(
    "a",
    [
      [2, 2000],
      [1, 1000],
    ],
    [
      [1, 900, 0.9],
      [2, null],
      [3, 3000, 0.5],
    ],
  ),
];

describe("lineRows", () => {
  test("gives one row per labeled line, in line order, with stage 1", () => {
    expect(lineRows(stageOne, null)).toEqual([
      {
        slug: "a",
        lines: [
          { line: 1, trueMs: 1000, stage1Ms: 900, stage1Confidence: 0.9 },
          { line: 2, trueMs: 2000, stage1Ms: null, stage1Confidence: null },
        ],
      },
    ]);
  });

  test("adds stage 2 when it was measured", () => {
    const stageTwo = [
      song(
        "a",
        [
          [1, 1000],
          [2, 2000],
        ],
        [
          [1, 1100, 0.6],
          [2, 2050, 0],
        ],
      ),
    ];
    const [first] = lineRows(stageOne, stageTwo);
    expect(first?.lines[0]).toEqual({
      line: 1,
      trueMs: 1000,
      stage1Ms: 900,
      stage1Confidence: 0.9,
      stage2Ms: 1100,
      stage2Confidence: 0.6,
    });
  });

  test("rejects stage 2 results for other songs", () => {
    const other = [song("b", [[1, 1000]], [[1, 1000]])];
    expect(() => lineRows(stageOne, other)).toThrow("song b");
  });
});
