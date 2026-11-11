import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { closeSync, writeSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openRunLog } from "../src/run-log";

let dir: string;

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), "run-log-"));
});

afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

/** A path that cannot be opened: its parent is a regular file. */
async function blockedPath(): Promise<string> {
  const file = join(dir, "file");
  await writeFile(file, "");
  return join(file, "logs", "a.log");
}

describe("openRunLog", () => {
  test("writes text and bytes to the file", async () => {
    const path = join(dir, "logs", "a.log");
    const log = openRunLog(path, () => {});
    log.write("a\n");
    log.write(new TextEncoder().encode("曲\n"));
    log.close();
    expect(await readFile(path, "utf8")).toBe("a\n曲\n");
  });

  test("replaces an earlier log", async () => {
    const path = join(dir, "a.log");
    await writeFile(path, "old\n");
    const log = openRunLog(path, () => {});
    log.write("new\n");
    log.close();
    expect(await readFile(path, "utf8")).toBe("new\n");
  });

  test("names the path when it cannot open the file", async () => {
    const path = await blockedPath();
    const warnings: string[] = [];
    openRunLog(path, (message) => warnings.push(message));
    expect(warnings).toEqual([
      expect.stringContaining(`cannot write the log ${path}`),
    ]);
  });

  test("reports no path when it cannot open the file", async () => {
    const log = openRunLog(await blockedPath(), () => {});
    expect(log.path).toBeNull();
  });

  test("ignores writes when it cannot open the file", async () => {
    const log = openRunLog(await blockedPath(), () => {});
    expect(() => {
      log.write("a\n");
      log.close();
    }).not.toThrow();
  });

  test("ignores writes after closing", async () => {
    const path = join(dir, "a.log");
    const log = openRunLog(path, () => {});
    log.close();
    log.write("a\n");
    expect(await readFile(path, "utf8")).toBe("");
  });

  test("warns once when a write fails", () => {
    const warnings: string[] = [];
    const failing = () => {
      throw new Error("disk full");
    };
    const log = openRunLog(
      join(dir, "a.log"),
      (message) => warnings.push(message),
      { write: failing, close: closeSync },
    );
    log.write("a\n");
    log.write("b\n");
    log.close();
    expect(warnings).toHaveLength(1);
  });

  test("reports no path after a write fails", () => {
    const failing = () => {
      throw new Error("disk full");
    };
    const log = openRunLog(join(dir, "a.log"), () => {}, {
      write: failing,
      close: closeSync,
    });
    log.write("a\n");
    log.close();
    expect(log.path).toBeNull();
  });

  test("warns instead of throwing when it cannot close the file", () => {
    const warnings: string[] = [];
    const log = openRunLog(
      join(dir, "a.log"),
      (message) => warnings.push(message),
      {
        write: (fd, chunk) => writeSync(fd, String(chunk)),
        close: (fd) => {
          closeSync(fd);
          throw new Error("close failed");
        },
      },
    );
    log.close();
    expect(warnings).toEqual([expect.stringContaining("cannot close the log")]);
  });
});
