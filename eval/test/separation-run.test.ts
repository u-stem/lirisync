import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { SongPlan } from "../src/separation-plan";
import {
  type SeparateRequest,
  type SeparationDeps,
  type SeparationModel,
  separateSongs,
} from "../src/separation-run";

let dir: string;

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), "lirisync-run-"));
  await mkdir(join(dir, "a", "audio"), { recursive: true });
  await mkdir(join(dir, "b", "audio"), { recursive: true });
});

afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

const MODEL: SeparationModel = {
  path: "/models/sep.onnx",
  name: "sep.onnx",
  sha256: "ab12",
};

const RESULT = { durationMs: 185_000, sampleRate: 44100, channels: 2 };

function separate(slug: string): SongPlan {
  const audio = join(dir, slug, "audio");
  return {
    kind: "separate",
    slug,
    input: join(audio, "mix.mp3"),
    inputName: "mix.mp3",
    output: join(audio, "vocals.wav"),
    metaPath: join(audio, "vocals.meta.json"),
  };
}

function setup(request: SeparateRequest = async () => RESULT) {
  const out: string[] = [];
  let clock = 0;
  const deps: SeparationDeps = {
    request,
    write: (text) => out.push(text),
    tty: false,
    now: () => {
      clock += 2500;
      return clock;
    },
  };
  return { out, deps };
}

async function exists(path: string): Promise<boolean> {
  return access(path).then(
    () => true,
    () => false,
  );
}

describe("separateSongs", () => {
  test("asks the worker with absolute paths and the model", async () => {
    const calls: unknown[] = [];
    const { deps } = setup(async (params) => {
      calls.push(params);
      return RESULT;
    });
    await separateSongs([separate("a")], MODEL, "0.1.0", deps);
    expect(calls).toEqual([
      {
        input: join(dir, "a", "audio", "mix.mp3"),
        output: join(dir, "a", "audio", "vocals.wav"),
        model: "/models/sep.onnx",
      },
    ]);
  });

  test("writes the metadata before it asks the worker", async () => {
    let existedAtRequest = false;
    const { deps } = setup(async () => {
      existedAtRequest = await exists(
        join(dir, "a", "audio", "vocals.meta.json"),
      );
      return RESULT;
    });
    await separateSongs([separate("a")], MODEL, "0.1.0", deps);
    expect(existedAtRequest).toBe(true);
  });

  test("removes the vocals it replaces before it writes the metadata", async () => {
    // A failed overwrite must not leave the new metadata beside the old vocals.
    const vocals = join(dir, "a", "audio", "vocals.wav");
    await writeFile(vocals, "old");
    const { deps } = setup(async () => {
      throw new Error("internal: boom");
    });
    await separateSongs([separate("a")], MODEL, "0.1.0", deps).catch(() => {});
    expect(await exists(vocals)).toBe(false);
  });

  test("records the input, model, its hash and the worker", async () => {
    const { deps } = setup();
    await separateSongs([separate("a")], MODEL, "0.1.0", deps);
    const text = await readFile(
      join(dir, "a", "audio", "vocals.meta.json"),
      "utf8",
    );
    expect(JSON.parse(text)).toEqual({
      input: "mix.mp3",
      model: "sep.onnx",
      modelSha256: "ab12",
      worker: "0.1.0",
    });
  });

  test("logs the duration and the time taken", async () => {
    const { deps, out } = setup();
    await separateSongs([separate("a")], MODEL, "0.1.0", deps);
    expect(out).toEqual(["[1/1] a: 3:05 separated in 2.5 s\n"]);
  });

  test("numbers the songs among all of them", async () => {
    const { deps, out } = setup();
    await separateSongs([separate("a"), separate("b")], MODEL, "w", deps);
    expect(out.at(-1)).toStartWith("[2/2] b:");
  });

  test("shows the progress the worker reports", async () => {
    const { deps, out } = setup(async (_params, onProgress) => {
      onProgress({
        id: "1",
        type: "progress",
        stage: "separate",
        ratio: 0.5,
        etaMs: null,
      });
      return RESULT;
    });
    await separateSongs([separate("a")], MODEL, "0.1.0", deps);
    expect(out[0]).toBe("[1/1] a: 50%\n");
  });

  test("skips a song without asking the worker or writing metadata", async () => {
    const calls: unknown[] = [];
    const { deps } = setup(async (params) => {
      calls.push(params);
      return RESULT;
    });
    await separateSongs(
      [{ kind: "skip", slug: "a", existing: "vocals.wav" }],
      MODEL,
      "0.1.0",
      deps,
    );
    expect(calls).toEqual([]);
  });

  test("logs a skipped song", async () => {
    const { deps, out } = setup();
    await separateSongs(
      [{ kind: "skip", slug: "a", existing: "vocals.wav" }],
      MODEL,
      "0.1.0",
      deps,
    );
    expect(out).toEqual(["[1/1] a: skipped, audio/vocals.wav exists\n"]);
  });

  test("names the song and the way to resume when the worker fails", async () => {
    const { deps } = setup(async () => {
      throw new Error("audio_unreadable: bad file");
    });
    const outcome = separateSongs([separate("a")], MODEL, "0.1.0", deps);
    await expect(outcome).rejects.toThrow(
      "a: audio_unreadable: bad file (run again with --skip-existing",
    );
  });

  test("stops at the first failure", async () => {
    const calls: unknown[] = [];
    const { deps } = setup(async (params) => {
      calls.push(params);
      throw new Error("boom");
    });
    await separateSongs([separate("a"), separate("b")], MODEL, "w", deps).catch(
      () => {},
    );
    expect(calls).toHaveLength(1);
  });

  test("rejects a result that is not a separate result", async () => {
    const { deps } = setup(async () => ({ durationMs: 1 }));
    const outcome = separateSongs([separate("a")], MODEL, "0.1.0", deps);
    await expect(outcome).rejects.toThrow(
      "a: The separate result is not usable",
    );
  });

  test("ends a terminal progress line before it fails", async () => {
    const { deps, out } = setup(async (_params, onProgress) => {
      onProgress({
        id: "1",
        type: "progress",
        stage: "separate",
        ratio: 0.5,
        etaMs: null,
      });
      throw new Error("boom");
    });
    await separateSongs([separate("a")], MODEL, "w", {
      ...deps,
      tty: true,
    }).catch(() => {});
    expect(out.at(-1)).toBe("\n");
  });
});
