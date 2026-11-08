import { handshake, WorkerClient } from "./worker-client";
import type { HelloResult } from "./worker-protocol";

export type RunningWorker = {
  client: WorkerClient;
  hello: HelloResult;
  /** Asks the worker to shut down and resolves with its exit code. */
  stop(): Promise<number>;
};

/**
 * Starts the worker as a child process and checks that it offers `required`.
 * The worker's stderr (its log) goes to this process's stderr, and so does
 * any stray stdout line without the protocol prefix.
 */
export async function startWorker(
  command: readonly string[],
  required: readonly string[],
): Promise<RunningWorker> {
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
      await client.request("shutdown", {});
      await client.close();
      return child.exited;
    },
  };
}
