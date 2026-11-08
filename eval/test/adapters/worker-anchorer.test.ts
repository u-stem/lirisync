import { describe, expect, test } from "bun:test";
import { type AnchorRequest, parseMs } from "@lirisync/core";
import { WorkerAnchorer } from "../../adapters/worker-anchorer";
import { WorkerProtocolError } from "../../adapters/worker-client";

type Call = { method: string; params: Record<string, unknown> };

/**
 * A client that records the call and answers with `result`. The real client
 * hands back whatever object the worker sent; shape checks are the anchorer's.
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

const request: AnchorRequest = {
  lyrics: ["風が吹く"],
  words: [{ start: parseMs(1000), end: parseMs(1800), text: "風が吹く" }],
  ignored: ["♪"],
};

function wireLine(fields: object = {}) {
  return {
    status: "anchor",
    startMs: 1000,
    endMs: 1800,
    matchRatio: 1,
    ambiguous: false,
    ...fields,
  };
}

describe("WorkerAnchorer", () => {
  test("calls the anchor method", async () => {
    const client = fakeClient({ lines: [wireLine()] });
    await new WorkerAnchorer(client).anchor(request);
    expect(client.calls[0]?.method).toBe("anchor");
  });

  test("sends word times in milliseconds under the protocol's names", async () => {
    const client = fakeClient({ lines: [wireLine()] });
    await new WorkerAnchorer(client).anchor(request);
    expect(client.calls[0]?.params).toEqual({
      lyrics: ["風が吹く"],
      words: [{ startMs: 1000, endMs: 1800, text: "風が吹く" }],
      ignored: ["♪"],
    });
  });

  test("returns an anchored line with its times", async () => {
    const client = fakeClient({ lines: [wireLine()] });
    const lines = await new WorkerAnchorer(client).anchor(request);
    expect(lines).toEqual([
      {
        status: "anchor",
        start: parseMs(1000),
        end: parseMs(1800),
        matchRatio: 1,
        ambiguous: false,
      },
    ]);
  });

  test("returns an unmatched line without times", async () => {
    const unmatched = wireLine({
      status: "unmatched",
      startMs: null,
      endMs: null,
      matchRatio: 0.2,
      ambiguous: true,
    });
    const client = fakeClient({ lines: [unmatched] });
    const lines = await new WorkerAnchorer(client).anchor(request);
    expect(lines).toEqual([
      { status: "unmatched", matchRatio: 0.2, ambiguous: true },
    ]);
  });

  test("returns a line that is not sung", async () => {
    const notSung = wireLine({
      status: "not_sung",
      startMs: null,
      endMs: null,
      matchRatio: 0,
    });
    const client = fakeClient({ lines: [notSung] });
    const lines = await new WorkerAnchorer(client).anchor(request);
    expect(lines).toEqual([{ status: "not_sung" }]);
  });

  test.each([
    ["is not an anchor result", { lines: [wireLine({ status: "x" })] }],
    ["has fewer lines than the lyrics", { lines: [] }],
    ["has an anchor without a start", { lines: [wireLine({ startMs: null })] }],
    [
      "has an unmatched line with an end",
      {
        lines: [wireLine({ status: "unmatched", startMs: null, endMs: 5 })],
      },
    ],
    [
      "has a line ending before it starts",
      { lines: [wireLine({ startMs: 2000, endMs: 1000 })] },
    ],
  ])("rejects a result that %s", async (_, result) => {
    const client = fakeClient(result);
    const outcome = new WorkerAnchorer(client).anchor(request);
    await expect(outcome).rejects.toBeInstanceOf(WorkerProtocolError);
  });
});
