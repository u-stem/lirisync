import { describe, expect, test } from "bun:test";
import { parseMs } from "@lirisync/core";
import {
  createProgressReporter,
  formatClock,
  formatProgress,
} from "../src/separation-progress";

describe("formatClock", () => {
  test("writes minutes and zero-padded seconds", () => {
    expect(formatClock(185_000)).toBe("3:05");
  });

  test("writes zero as 0:00", () => {
    expect(formatClock(0)).toBe("0:00");
  });

  test("rounds to the nearest second", () => {
    expect(formatClock(1_600)).toBe("0:02");
  });

  test("goes past an hour in minutes", () => {
    expect(formatClock(3_725_000)).toBe("62:05");
  });
});

describe("formatProgress", () => {
  test("shows position, slug, percent and eta", () => {
    expect(formatProgress("song", 2, 5, 0.42, 65_000)).toBe(
      "[2/5] song: 42% (eta 1:05)",
    );
  });

  test("leaves out the eta when it is unknown", () => {
    expect(formatProgress("song", 1, 1, 0.5, null)).toBe("[1/1] song: 50%");
  });

  test("rounds the percent down", () => {
    expect(formatProgress("song", 1, 1, 0.999, null)).toBe("[1/1] song: 99%");
  });
});

function reporter(tty: boolean) {
  const out: string[] = [];
  const r = createProgressReporter({
    slug: "s",
    index: 1,
    total: 1,
    tty,
    write: (text) => out.push(text),
  });
  return { out, ...r };
}

const at = (ratio: number) => ({ ratio, etaMs: null });

describe("createProgressReporter on a terminal", () => {
  test("overwrites the line with a carriage return", () => {
    const r = reporter(true);
    r.update(at(0.1));
    expect(r.out).toEqual(["\r[1/1] s: 10%"]);
  });

  test("writes only when the integer percent changes", () => {
    const r = reporter(true);
    r.update(at(0.101));
    r.update(at(0.109));
    expect(r.out).toHaveLength(1);
  });

  test("writes each new percent", () => {
    const r = reporter(true);
    r.update(at(0.1));
    r.update(at(0.11));
    expect(r.out).toHaveLength(2);
  });

  test("pads a shorter line so nothing of the last one stays", () => {
    const r = reporter(true);
    r.update({ ratio: 0.5, etaMs: parseMs(5_000) });
    r.update({ ratio: 0.51, etaMs: null });
    expect(r.out[1]).toBe(
      `\r${"[1/1] s: 51%".padEnd("[1/1] s: 50% (eta 0:05)".length)}`,
    );
  });

  test("ends the line when finished", () => {
    const r = reporter(true);
    r.update(at(0.1));
    r.finish();
    expect(r.out.at(-1)).toBe("\n");
  });

  test("writes nothing on finish when nothing was shown", () => {
    const r = reporter(true);
    r.finish();
    expect(r.out).toEqual([]);
  });
});

describe("createProgressReporter without a terminal", () => {
  test("writes a line for the first report", () => {
    const r = reporter(false);
    r.update(at(0.03));
    expect(r.out).toEqual(["[1/1] s: 3%\n"]);
  });

  test("writes nothing within the same 10 % step", () => {
    const r = reporter(false);
    r.update(at(0.11));
    r.update(at(0.19));
    expect(r.out).toHaveLength(1);
  });

  test("writes again when a new 10 % step is entered", () => {
    const r = reporter(false);
    r.update(at(0.11));
    r.update(at(0.2));
    expect(r.out).toHaveLength(2);
  });

  test("writes the step even when the ratio jumps over a multiple of 10", () => {
    const r = reporter(false);
    r.update(at(0.05));
    r.update(at(0.37));
    expect(r.out.at(-1)).toBe("[1/1] s: 37%\n");
  });

  test("adds nothing on finish", () => {
    const r = reporter(false);
    r.update(at(0.5));
    r.finish();
    expect(r.out).toHaveLength(1);
  });
});
