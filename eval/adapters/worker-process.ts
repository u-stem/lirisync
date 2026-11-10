import { join } from "node:path";
import { handshake, WorkerClient } from "./worker-client";
import type { HelloResult } from "./worker-protocol";

export type RunningWorker = {
  client: WorkerClient;
  hello: HelloResult;
  /**
   * Asks the worker to shut down and resolves with its exit code. A worker
   * that fails or does not answer in time is killed, so this never throws
   * and the exit code is the only sign of trouble.
   */
  stop(): Promise<number>;
};

export type StartWorkerOptions = {
  /**
   * How long `stop` waits for the answer to shutdown, and then for the exit,
   * before killing the worker.
   */
  shutdownTimeoutMs?: number;
};

/** The command that runs the alignment worker from the repository at `repoRoot`. */
export function alignWorkerCommand(repoRoot: string): string[] {
  return [
    "uv",
    "--directory",
    join(repoRoot, "workers", "align"),
    "run",
    "lirisync-worker",
  ];
}

const DEFAULT_SHUTDOWN_TIMEOUT_MS = 10_000;

/** Resolves with what `promise` settles to, or `late` after `timeoutMs`. */
async function within<T>(
  promise: Promise<T>,
  timeoutMs: number,
  late: T,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<T>((resolve) => {
    timer = setTimeout(() => resolve(late), timeoutMs);
  });
  try {
    return await Promise.race([promise, deadline]);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Starts the worker as a child process and checks that it offers `required`.
 * The worker's stderr (its log) goes to this process's stderr, and so does
 * any stray stdout line without the protocol prefix.
 */
export async function startWorker(
  command: readonly string[],
  required: readonly string[],
  options: StartWorkerOptions = {},
): Promise<RunningWorker> {
  const timeoutMs = options.shutdownTimeoutMs ?? DEFAULT_SHUTDOWN_TIMEOUT_MS;
  const child = Bun.spawn([...command], {
    stdin: "pipe",
    stdout: "pipe",
    stderr: "inherit",
  });
  const client = new WorkerClient(
    { stdin: child.stdin, stdout: child.stdout },
    { onLog: (line) => process.stderr.write(`worker: ${line}\n`) },
  );
  let hello: HelloResult;
  try {
    hello = await handshake(client, required);
  } catch (error) {
    child.kill();
    throw error;
  }
  return {
    client,
    hello,
    async stop() {
      const shutdown = client.request("shutdown", {}).then(
        () => true,
        () => false,
      );
      const answered = await within(shutdown, timeoutMs, false);
      // Ending the input of a worker that already exited can fail; the exit
      // code below is what reports that.
      await client.close().catch(() => {});
      // A worker can answer and still not exit, e.g. on a leftover thread.
      const exited = answered
        ? await within(
            child.exited.then(() => true),
            timeoutMs,
            false,
          )
        : false;
      if (!exited) child.kill();
      return child.exited;
    },
  };
}
