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
  /** How long `stop` waits for the answer to shutdown before killing. */
  shutdownTimeoutMs?: number;
};

const DEFAULT_SHUTDOWN_TIMEOUT_MS = 10_000;

/** Resolves true when the worker answers shutdown in time, false otherwise. */
async function askToShutDown(
  client: WorkerClient,
  timeoutMs: number,
): Promise<boolean> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<false>((resolve) => {
    timer = setTimeout(() => resolve(false), timeoutMs);
  });
  const answered = client.request("shutdown", {}).then(
    () => true,
    () => false,
  );
  try {
    return await Promise.race([answered, late]);
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
      const answered = await askToShutDown(client, timeoutMs);
      // Ending the input of a worker that already exited can fail; the exit
      // code below is what reports that.
      await client.close().catch(() => {});
      if (!answered) child.kill();
      return child.exited;
    },
  };
}
