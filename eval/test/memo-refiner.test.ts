import { describe, expect, test } from "bun:test";
import {
  type LineWindow,
  parseMs,
  type RefinedLine,
  type RefineRequest,
  type Refiner,
} from "@lirisync/core";
import { MemoRefiner } from "../src/memo-refiner";

/**
 * Records each request. A line with a window comes back refined at a start
 * that depends on the call number and the line, so a reused result can be told
 * from a fresh one; a line without a window is `no_window`.
 */
class RecordingRefiner implements Refiner {
  readonly requests: RefineRequest[] = [];

  async refine(request: RefineRequest): Promise<RefinedLine[]> {
    this.requests.push(request);
    const call = this.requests.length;
    return request.windows.map(
      (window, index): RefinedLine =>
        window === null
          ? { status: "no_window", skippedChars: 0 }
          : {
              status: "refined",
              start: parseMs(call * 1000 + index),
              end: parseMs(call * 1000 + index + 500),
              logRatio: 0,
              skippedChars: 0,
            },
    );
  }
}

function window(start: number, end: number): LineWindow {
  return { start: parseMs(start), end: parseMs(end) };
}

function request(overrides: Partial<RefineRequest> = {}): RefineRequest {
  return {
    audioPath: "vocals.wav",
    modelDir: "model",
    lyrics: ["a", "b", "c"],
    windows: [window(0, 1000), window(2000, 3000), null],
    spelling: "surface",
    ignored: [],
    margin: parseMs(1000),
    ...overrides,
  };
}

describe("MemoRefiner", () => {
  test("passes the windows through on the first request", async () => {
    const inner = new RecordingRefiner();
    await new MemoRefiner(inner).refine(request());
    expect(inner.requests[0]?.windows).toEqual(request().windows);
  });

  test("sends every lyric line, remembered or not", async () => {
    const inner = new RecordingRefiner();
    const memo = new MemoRefiner(inner);
    await memo.refine(request());
    await memo.refine(request({ windows: [window(0, 1000), null, null] }));
    expect(inner.requests[1]?.lyrics).toEqual(["a", "b", "c"]);
  });

  test("does not call the inner refiner for a request it has answered", async () => {
    const inner = new RecordingRefiner();
    const memo = new MemoRefiner(inner);
    await memo.refine(request());
    await memo.refine(request());
    expect(inner.requests).toHaveLength(1);
  });

  test("gives the same result for a request it has answered", async () => {
    const memo = new MemoRefiner(new RecordingRefiner());
    const first = await memo.refine(request());
    const second = await memo.refine(request());
    expect(second).toEqual(first);
  });

  test("sends only the window of the line that changed", async () => {
    const inner = new RecordingRefiner();
    const memo = new MemoRefiner(inner);
    await memo.refine(request());
    await memo.refine(
      request({ windows: [window(0, 1000), window(2100, 3000), null] }),
    );
    expect(inner.requests[1]?.windows).toEqual([
      null,
      window(2100, 3000),
      null,
    ]);
  });

  test("returns remembered and new results in line order", async () => {
    const memo = new MemoRefiner(new RecordingRefiner());
    await memo.refine(request());
    const second = await memo.refine(
      request({ windows: [window(0, 1000), window(2100, 3000), null] }),
    );
    // Line 1 is from call 1, line 2 from call 2, line 3 is no_window.
    expect(
      second.map((line) => (line.status === "refined" ? line.start : null)),
    ).toEqual([parseMs(1000), parseMs(2001), null]);
  });

  test("sends a line again when its text differs under the same window", async () => {
    const inner = new RecordingRefiner();
    const memo = new MemoRefiner(inner);
    await memo.refine(request());
    await memo.refine(request({ lyrics: ["a", "x", "c"] }));
    expect(inner.requests[1]?.windows).toEqual([
      null,
      window(2000, 3000),
      null,
    ]);
  });

  test("sends the lines again when the margin differs", async () => {
    const inner = new RecordingRefiner();
    const memo = new MemoRefiner(inner);
    await memo.refine(request());
    await memo.refine(request({ margin: parseMs(500) }));
    expect(inner.requests[1]?.windows).toEqual(request().windows);
  });

  test("sends the lines again when the spelling differs", async () => {
    const inner = new RecordingRefiner();
    const memo = new MemoRefiner(inner);
    await memo.refine(request());
    await memo.refine(request({ spelling: "kana" }));
    expect(inner.requests[1]?.windows).toEqual(request().windows);
  });

  test("sends the lines again when the audio differs", async () => {
    const inner = new RecordingRefiner();
    const memo = new MemoRefiner(inner);
    await memo.refine(request());
    await memo.refine(request({ audioPath: "other.wav" }));
    expect(inner.requests[1]?.windows).toEqual(request().windows);
  });

  test("throws when the inner refiner returns another number of lines", async () => {
    const inner: Refiner = { refine: async () => [] };
    const run = new MemoRefiner(inner).refine(request());
    await expect(run).rejects.toThrow("returned 0 lines for 3 lyric lines");
  });

  test("throws when the windows and the lyrics differ in number", async () => {
    const run = new MemoRefiner(new RecordingRefiner()).refine(
      request({ windows: [null] }),
    );
    await expect(run).rejects.toThrow("1 windows for 3 lyric lines");
  });
});
