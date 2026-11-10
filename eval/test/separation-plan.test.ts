import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  assertPlanOptions,
  formatMeta,
  type PlanOptions,
  planSong,
} from "../src/separation-plan";

let dir: string;

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), "lirisync-separate-"));
});

afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

async function addAudio(slug: string, ...names: string[]): Promise<void> {
  await mkdir(join(dir, slug, "audio"), { recursive: true });
  for (const name of names) {
    await writeFile(join(dir, slug, "audio", name), "x");
  }
}

const DEFAULTS: PlanOptions = {
  inputStem: "mix",
  overwrite: false,
  skipExisting: false,
};

function plan(slug: string, options: Partial<PlanOptions> = {}) {
  return planSong(dir, slug, { ...DEFAULTS, ...options });
}

describe("assertPlanOptions", () => {
  test("accepts the defaults", () => {
    expect(() => assertPlanOptions(DEFAULTS)).not.toThrow();
  });

  test("rejects --overwrite together with --skip-existing", () => {
    expect(() =>
      assertPlanOptions({ ...DEFAULTS, overwrite: true, skipExisting: true }),
    ).toThrow("--overwrite and --skip-existing");
  });

  test("rejects vocals as the input", () => {
    expect(() =>
      assertPlanOptions({ ...DEFAULTS, inputStem: "vocals" }),
    ).toThrow("--input");
  });

  test("rejects vocals in any case as the input", () => {
    expect(() =>
      assertPlanOptions({ ...DEFAULTS, inputStem: "VoCaLs" }),
    ).toThrow("--input");
  });
});

describe("planSong without existing vocals", () => {
  test("separates", async () => {
    await addAudio("a", "mix.mp3");
    expect((await plan("a")).kind).toBe("separate");
  });

  test("reads the input file", async () => {
    await addAudio("a", "mix.mp3");
    expect(await plan("a")).toMatchObject({
      input: join(dir, "a", "audio", "mix.mp3"),
    });
  });

  test("names the input file", async () => {
    await addAudio("a", "mix.mp3");
    expect(await plan("a")).toMatchObject({ inputName: "mix.mp3" });
  });

  test("writes audio/vocals.wav", async () => {
    await addAudio("a", "mix.mp3");
    expect(await plan("a")).toMatchObject({
      output: join(dir, "a", "audio", "vocals.wav"),
    });
  });

  test("puts the meta file beside the audio", async () => {
    await addAudio("a", "mix.mp3");
    expect(await plan("a")).toMatchObject({
      metaPath: join(dir, "a", "audio", "vocals.meta.json"),
    });
  });

  test("compares the input stem without case", async () => {
    await addAudio("a", "MIX.FLAC");
    expect(await plan("a")).toMatchObject({ inputName: "MIX.FLAC" });
  });

  test("uses the stem given by --input", async () => {
    await addAudio("a", "mix.mp3", "full.wav");
    expect(await plan("a", { inputStem: "full" })).toMatchObject({
      inputName: "full.wav",
    });
  });

  test("does not count vocals.meta.json as vocals", async () => {
    await addAudio("a", "mix.mp3", "vocals.meta.json");
    expect((await plan("a")).kind).toBe("separate");
  });

  test("rejects a song without an input", async () => {
    await addAudio("a", "other.wav");
    await expect(plan("a")).rejects.toThrow("a: no audio file audio/mix.*");
  });

  test("rejects a song without an audio directory", async () => {
    await mkdir(join(dir, "a"));
    await expect(plan("a")).rejects.toThrow("a: no audio file");
  });

  test("rejects two input files", async () => {
    await addAudio("a", "mix.mp3", "mix.wav");
    await expect(plan("a")).rejects.toThrow("more than one");
  });

  test("ignores a directory named like the input", async () => {
    await addAudio("a", "mix.wav");
    await mkdir(join(dir, "a", "audio", "mix.d"));
    expect((await plan("a")).kind).toBe("separate");
  });
});

describe("planSong with existing vocals", () => {
  test("rejects vocals.wav without --overwrite and names the flag", async () => {
    await addAudio("a", "mix.mp3", "vocals.wav");
    await expect(plan("a")).rejects.toThrow("--overwrite");
  });

  test("rejects vocals.wav without --overwrite and names the file", async () => {
    await addAudio("a", "mix.mp3", "vocals.wav");
    await expect(plan("a")).rejects.toThrow("vocals.wav");
  });

  test("replaces vocals.wav with --overwrite", async () => {
    await addAudio("a", "mix.mp3", "vocals.wav");
    expect(await plan("a", { overwrite: true })).toMatchObject({
      output: join(dir, "a", "audio", "vocals.wav"),
    });
  });

  test("replaces the file under its own spelling with --overwrite", async () => {
    await addAudio("a", "mix.mp3", "Vocals.WAV");
    expect(await plan("a", { overwrite: true })).toMatchObject({
      output: join(dir, "a", "audio", "Vocals.WAV"),
    });
  });

  test("rejects vocals in another format even with --overwrite", async () => {
    await addAudio("a", "mix.mp3", "vocals.flac");
    await expect(plan("a", { overwrite: true })).rejects.toThrow("vocals.flac");
  });

  test("rejects vocals in another format without --overwrite", async () => {
    await addAudio("a", "mix.mp3", "vocals.mp3");
    await expect(plan("a")).rejects.toThrow("not a .wav");
  });

  test("rejects two vocals files even with --overwrite", async () => {
    await addAudio("a", "mix.mp3", "vocals.wav", "vocals.mp3");
    await expect(plan("a", { overwrite: true })).rejects.toThrow(
      "more than one",
    );
  });

  test("skips with --skip-existing", async () => {
    await addAudio("a", "mix.mp3", "vocals.wav");
    expect(await plan("a", { skipExisting: true })).toEqual({
      kind: "skip",
      slug: "a",
      existing: "vocals.wav",
    });
  });

  test("skips vocals in another format with --skip-existing", async () => {
    await addAudio("a", "mix.mp3", "vocals.flac");
    expect((await plan("a", { skipExisting: true })).kind).toBe("skip");
  });

  test("skips without needing an input with --skip-existing", async () => {
    await addAudio("a", "vocals.wav");
    expect((await plan("a", { skipExisting: true })).kind).toBe("skip");
  });

  test("still separates a song without vocals with --skip-existing", async () => {
    await addAudio("a", "mix.mp3");
    expect((await plan("a", { skipExisting: true })).kind).toBe("separate");
  });
});

describe("formatMeta", () => {
  const meta = {
    input: "mix.mp3",
    model: "sep.onnx",
    modelSha256: "ab",
    worker: "0.1.0",
  };

  test("writes two-space JSON with a final newline", () => {
    expect(formatMeta(meta)).toBe(`${JSON.stringify(meta, null, 2)}\n`);
  });

  test("keeps the keys in camelCase and in this order", () => {
    expect(Object.keys(JSON.parse(formatMeta(meta)))).toEqual([
      "input",
      "model",
      "modelSha256",
      "worker",
    ]);
  });
});
