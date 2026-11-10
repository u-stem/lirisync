import { describe, expect, test } from "bun:test";
import { parseMs, type RefineRequest } from "@lirisync/core";
import { WorkerProtocolError } from "../../adapters/worker-client";
import { WorkerRefiner } from "../../adapters/worker-refiner";

type Call = { method: string; params: Record<string, unknown> };

/**
 * A client that records the call and answers with `result`. The real client
 * hands back whatever object the worker sent; shape checks are the refiner's.
 */
function fakeClient(result: Record<string, unknown>) {
  const calls: Call[] = [];
  return {
    calls,
    async request(method: string, params: Record<string, unknown>) {
      calls.push({ method, params });
      return result;
    },
  };
}

const request: RefineRequest = {
  audioPath: "/songs/a/audio/vocals.wav",
  modelDir: "/models/aligner",
  lyrics: ["風が吹く", "（間奏）"],
  windows: [{ start: parseMs(1000), end: parseMs(1800) }, null],
  spelling: "kana",
  ignored: ["♪"],
  margin: parseMs(500),
};

function wireLine(fields: object = {}) {
  return {
    status: "refined",
    startMs: 1100,
    endMs: 1700,
    logRatio: -0.25,
    skippedChars: 1,
    ...fields,
  };
}

function noWindow(fields: object = {}) {
  return wireLine({
    status: "no_window",
    startMs: null,
    endMs: null,
    logRatio: null,
    skippedChars: 0,
    ...fields,
  });
}

const oneLine: RefineRequest = {
  ...request,
  lyrics: ["風が吹く"],
  windows: [{ start: parseMs(1000), end: parseMs(1800) }],
};

describe("WorkerRefiner", () => {
  test("calls the refine method", async () => {
    const client = fakeClient({ lines: [wireLine(), noWindow()] });
    await new WorkerRefiner(client).refine(request);
    expect(client.calls[0]?.method).toBe("refine");
  });

  test("sends the request under the protocol's names", async () => {
    const client = fakeClient({ lines: [wireLine(), noWindow()] });
    await new WorkerRefiner(client).refine(request);
    expect(client.calls[0]?.params).toEqual({
      audio: "/songs/a/audio/vocals.wav",
      model: "/models/aligner",
      lyrics: ["風が吹く", "（間奏）"],
      windows: [{ startMs: 1000, endMs: 1800 }, null],
      spelling: "kana",
      ignored: ["♪"],
      marginMs: 500,
    });
  });

  test("returns a refined line with its times and ratio", async () => {
    const client = fakeClient({ lines: [wireLine()] });
    const lines = await new WorkerRefiner(client).refine(oneLine);
    expect(lines).toEqual([
      {
        status: "refined",
        start: parseMs(1100),
        end: parseMs(1700),
        logRatio: -0.25,
        skippedChars: 1,
      },
    ]);
  });

  test("accepts a refined line that starts and ends together", async () => {
    const client = fakeClient({ lines: [wireLine({ endMs: 1100 })] });
    const lines = await new WorkerRefiner(client).refine(oneLine);
    expect(lines[0]?.status).toBe("refined");
  });

  test.each(["no_window", "no_text", "too_long", "too_short"])(
    "returns a %s line without times",
    async (status) => {
      const client = fakeClient({
        lines: [noWindow({ status, skippedChars: 2 })],
      });
      const lines = await new WorkerRefiner(client).refine(oneLine);
      expect(lines).toEqual([{ status, skippedChars: 2 }]);
    },
  );

  test.each([
    ["is not a refine result", { lines: [wireLine({ status: "x" })] }],
    ["has no lines for the lyrics", { lines: [] }],
    ["has more lines than the lyrics", { lines: [wireLine(), wireLine()] }],
    [
      "has a refined line without a start",
      { lines: [wireLine({ startMs: null })] },
    ],
    [
      "has a refined line without an end",
      { lines: [wireLine({ endMs: null })] },
    ],
    [
      "has a refined line without a ratio",
      { lines: [wireLine({ logRatio: null })] },
    ],
    [
      "has a refined line ending before it starts",
      { lines: [wireLine({ startMs: 2000, endMs: 1000 })] },
    ],
    ["has a ratio above zero", { lines: [wireLine({ logRatio: 0.5 })] }],
    [
      "has a skipped line with a start",
      { lines: [noWindow({ status: "too_short", startMs: 5 })] },
    ],
    [
      "has a skipped line with an end",
      { lines: [noWindow({ status: "no_text", endMs: 5 })] },
    ],
    [
      "has a skipped line with a ratio",
      { lines: [noWindow({ status: "too_long", logRatio: -1 })] },
    ],
  ])("rejects a result that %s", async (_, result) => {
    const client = fakeClient(result);
    const outcome = new WorkerRefiner(client).refine(oneLine);
    await expect(outcome).rejects.toBeInstanceOf(WorkerProtocolError);
  });
});
