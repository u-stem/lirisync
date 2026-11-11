import { closeSync, mkdirSync, openSync, writeSync } from "node:fs";
import { dirname } from "node:path";

export type RunLog = {
  /** The file written, or null when it could not be opened or a write failed. */
  readonly path: string | null;
  write(chunk: string | Uint8Array): void;
  close(): void;
};

/** The file operations, replaceable in tests. */
export type RunLogIo = {
  write(fd: number, chunk: string | Uint8Array): void;
  close(fd: number): void;
};

function writeChunk(fd: number, chunk: string | Uint8Array): void {
  // Split by type: writeSync's overloads take one or the other.
  if (typeof chunk === "string") writeSync(fd, chunk);
  else writeSync(fd, chunk);
}

function reasonOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Opens `path` afresh for a copy of what a run shows. The log only helps to
 * share the run, so a log that cannot be opened or written warns once through
 * `warn` and is dropped; it never stops the run.
 */
export function openRunLog(
  path: string,
  warn: (message: string) => void,
  io: RunLogIo = { write: writeChunk, close: closeSync },
): RunLog {
  let fd: number | null;
  try {
    mkdirSync(dirname(path), { recursive: true });
    fd = openSync(path, "w");
  } catch (error) {
    warn(`cannot write the log ${path}: ${reasonOf(error)}`);
    return { path: null, write() {}, close() {} };
  }
  let failed = false;
  return {
    // A log that stopped part way would mislead whoever reads it as the run.
    get path() {
      return failed ? null : path;
    },
    write(chunk) {
      if (fd === null || failed) return;
      try {
        io.write(fd, chunk);
      } catch (error) {
        warn(`stopped writing the log ${path}: ${reasonOf(error)}`);
        failed = true;
      }
    },
    close() {
      if (fd === null) return;
      const open = fd;
      fd = null;
      try {
        io.close(open);
      } catch (error) {
        warn(`cannot close the log ${path}: ${reasonOf(error)}`);
      }
    },
  };
}
