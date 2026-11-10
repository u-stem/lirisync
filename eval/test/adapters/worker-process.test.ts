import { describe, expect, test } from "bun:test";
import { WorkerProtocolError } from "../../adapters/worker-client";
import { alignWorkerCommand, startWorker } from "../../adapters/worker-process";

const FAKE_WORKER = `${import.meta.dir}/fixtures/fake-worker.ts`;

function fake(mode: string): string[] {
  return [process.execPath, FAKE_WORKER, mode];
}

describe("alignWorkerCommand", () => {
  test("runs the worker through uv in workers/align", () => {
    expect(alignWorkerCommand("/repo")).toEqual([
      "uv",
      "--directory",
      "/repo/workers/align",
      "run",
      "lirisync-worker",
    ]);
  });
});

describe("startWorker", () => {
  test("returns the worker's hello", async () => {
    const worker = await startWorker(fake("ok"), ["shutdown"]);
    await worker.stop();
    expect(worker.hello.worker).toBe("fake");
  });

  test("rejects a worker that speaks another protocol", async () => {
    const started = startWorker(fake("other-protocol"), []);
    await expect(started).rejects.toBeInstanceOf(WorkerProtocolError);
  });

  test("stop resolves with the exit code after shutdown", async () => {
    const worker = await startWorker(fake("ok"), []);
    expect(await worker.stop()).toBe(0);
  });

  test("stop resolves with the exit code of a worker that already exited", async () => {
    const worker = await startWorker(fake("exit-after-hello"), []);
    expect(await worker.stop()).toBe(3);
  });

  test("stop kills a worker that does not answer shutdown", async () => {
    const worker = await startWorker(fake("deaf"), [], {
      shutdownTimeoutMs: 100,
    });
    expect(await worker.stop()).not.toBe(0);
  });

  test("stop kills a worker that answers shutdown but does not exit", async () => {
    const worker = await startWorker(fake("lingering"), [], {
      shutdownTimeoutMs: 100,
    });
    expect(await worker.stop()).not.toBe(0);
  });
});
