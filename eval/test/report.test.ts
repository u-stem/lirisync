import { describe, expect, test } from "bun:test";
import { parseMs } from "@lirisync/core";
import { buildReport, formatReport, type SongResult } from "../src/report";

function result(
  slug: string,
  truthMs: number[],
  predictedMs: (number | null)[],
  lyricsText = "a\nb\nc\n",
): SongResult {
  return {
    slug,
    lyricsText,
    truth: truthMs.map((ms, i) => ({ line: i + 1, start: parseMs(ms) })),
    predictions: predictedMs.map((ms, i) => ({
      line: i + 1,
      start: ms === null ? null : parseMs(ms),
      confidence: 0.9,
    })),
  };
}

const good = result("good", [1000, 2000, 3000], [1100, 2100, 3100]);
const bad = result("bad", [1000, 2000], [null, null], "a\nb\n");

describe("buildReport", () => {
  test("pools all songs in the overall score", () => {
    const report = buildReport([good, bad]);
    expect(report.overall.score.labeled).toBe(5);
  });

  test("scores each song on its own", () => {
    const report = buildReport([good, bad]);
    expect(report.songs.map((song) => song.score.matched)).toEqual([3, 0]);
  });

  test("passes the gate when the pooled score is accurate", () => {
    const report = buildReport([good]);
    expect(report.overall.passesGate).toBe(true);
  });

  test("fails the gate when too few lines match", () => {
    const report = buildReport([good, bad]);
    expect(report.overall.passesGate).toBe(false);
  });

  test("counts repeats within each song, not across songs", () => {
    const repeated = result("rep", [1000, 9000], [1000, 9000], "la\nla\n");
    const other = result("other", [1000], [1000], "la\n");
    const report = buildReport([repeated, other]);
    expect(report.overall.repeats.considered).toBe(2);
  });
});

describe("formatReport", () => {
  test("shows the bias with its sign", () => {
    const text = formatReport(buildReport([good]));
    expect(text).toContain("  Bias (predicted - true, median): +100 ms");
  });

  test("shows a zero bias without a sign", () => {
    const exact = result("exact", [1000, 2000, 3000], [1000, 2000, 3000]);
    const text = formatReport(buildReport([exact]));
    expect(text).toContain("bias 0 ms");
  });

  test("shows a bias that rounds to minus zero without a sign", () => {
    // The median of -1 and 0 is -0.5, which Math.round makes -0.
    const nearly = result("nearly", [1000, 2000], [999, 2000], "a\nb\n");
    const text = formatReport(buildReport([nearly]));
    expect(text).toContain("bias 0 ms");
  });

  test("shows an early bias with a minus sign", () => {
    const early = result("early", [1000, 2000, 3000], [900, 1950, 2900]);
    const text = formatReport(buildReport([early]));
    expect(text).toContain("bias -100 ms");
  });

  test("states a passing verdict", () => {
    const text = formatReport(buildReport([good]));
    expect(text).toContain("Gate: PASS");
  });

  test("states a failing verdict", () => {
    const text = formatReport(buildReport([good, bad]));
    expect(text).toContain("Gate: FAIL");
  });

  test("lists each song by slug", () => {
    const text = formatReport(buildReport([good, bad]));
    expect(text).toContain("bad");
  });

  test("shows a missing value as a dash", () => {
    const text = formatReport(buildReport([bad]));
    expect(text).toContain("—");
  });
});
