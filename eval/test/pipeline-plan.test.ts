import { describe, expect, test } from "bun:test";
import { join, resolve } from "node:path";
import {
  type PipelineOptions,
  parsePipelineOptions,
  pipelineSteps,
} from "../src/pipeline-plan";

const REPO = resolve("repo-root");
const WIN_MODELS = "C:\\lirisync-models";

function options(overrides: Partial<PipelineOptions> = {}): PipelineOptions {
  return {
    modelsDir: resolve("models"),
    asrModel: "Systran/faster-whisper-large-v3",
    asr: "large-v3",
    outDir: resolve("out"),
    songsDir: resolve("songs"),
    songs: undefined,
    repoRoot: REPO,
    ...overrides,
  };
}

describe("parsePipelineOptions", () => {
  test("defaults the models directory on win32", () => {
    const parsed = parsePipelineOptions({}, "win32", REPO);
    expect(parsed.modelsDir).toBe(WIN_MODELS);
  });

  test("requires the models directory off win32", () => {
    expect(() => parsePipelineOptions({}, "darwin", REPO)).toThrow(
      "--models-dir is required",
    );
  });

  test("resolves a given models directory", () => {
    const parsed = parsePipelineOptions({ "models-dir": "m" }, "linux", REPO);
    expect(parsed.modelsDir).toBe(resolve("m"));
  });

  test("rejects an empty models directory", () => {
    expect(() =>
      parsePipelineOptions({ "models-dir": "" }, "win32", REPO),
    ).toThrow("--models-dir");
  });

  test("defaults the ASR model", () => {
    const parsed = parsePipelineOptions({}, "win32", REPO);
    expect(parsed.asrModel).toBe("Systran/faster-whisper-large-v3");
  });

  test("keeps a given ASR model as it is", () => {
    const parsed = parsePipelineOptions(
      { "asr-model": "org/model" },
      "win32",
      REPO,
    );
    expect(parsed.asrModel).toBe("org/model");
  });

  test("defaults the ASR name", () => {
    const parsed = parsePipelineOptions({}, "win32", REPO);
    expect(parsed.asr).toBe("large-v3");
  });

  test("rejects an invalid ASR name", () => {
    expect(() => parsePipelineOptions({ asr: "../x" }, "win32", REPO)).toThrow(
      "Invalid ASR name",
    );
  });

  test("defaults the output directory under the repository", () => {
    const parsed = parsePipelineOptions({}, "win32", REPO);
    expect(parsed.outDir).toBe(join(REPO, "eval", "results"));
  });

  test("resolves a given output directory", () => {
    const parsed = parsePipelineOptions({ "out-dir": "o" }, "win32", REPO);
    expect(parsed.outDir).toBe(resolve("o"));
  });

  test("defaults the songs directory under the repository", () => {
    const parsed = parsePipelineOptions({}, "win32", REPO);
    expect(parsed.songsDir).toBe(join(REPO, "eval", "songs"));
  });

  test("resolves a given songs directory", () => {
    const parsed = parsePipelineOptions({ "songs-dir": "s" }, "win32", REPO);
    expect(parsed.songsDir).toBe(resolve("s"));
  });

  test("leaves the songs unset by default", () => {
    const parsed = parsePipelineOptions({}, "win32", REPO);
    expect(parsed.songs).toBeUndefined();
  });

  test("keeps the given songs", () => {
    const parsed = parsePipelineOptions({ song: ["a", "b"] }, "win32", REPO);
    expect(parsed.songs).toEqual(["a", "b"]);
  });

  test("carries the repository root", () => {
    const parsed = parsePipelineOptions({}, "win32", REPO);
    expect(parsed.repoRoot).toBe(REPO);
  });
});

describe("pipelineSteps", () => {
  test("lists the four steps in order", () => {
    const names = pipelineSteps(options()).map((step) => step.name);
    expect(names).toEqual([
      "separate",
      "transcribe",
      "eval surface",
      "eval kana",
    ]);
  });

  test("runs the commands by name", () => {
    const commands = pipelineSteps(options()).map((step) => step.command);
    expect(commands).toEqual(["bun", "uv", "bun", "bun"]);
  });

  test("separates with the separator model", () => {
    const opts = options();
    const [separate] = pipelineSteps(opts);
    expect(separate?.args).toEqual([
      join(REPO, "eval", "separate.ts"),
      "--model",
      join(opts.modelsDir, "separator", "sep-all-int8.onnx"),
      "--songs-dir",
      opts.songsDir,
      "--skip-existing",
    ]);
  });

  test("transcribes with the ASR model and name", () => {
    const opts = options();
    const transcribe = pipelineSteps(opts)[1];
    expect(transcribe?.args).toEqual([
      "--directory",
      join(REPO, "eval", "transcribe"),
      "run",
      "lirisync-transcribe",
      "--model",
      "Systran/faster-whisper-large-v3",
      "--name",
      "large-v3",
      "--songs-dir",
      opts.songsDir,
      "--skip-existing",
    ]);
  });

  test("evaluates with surface spelling", () => {
    const opts = options();
    const surface = pipelineSteps(opts)[2];
    expect(surface?.args).toEqual([
      join(REPO, "eval", "run.ts"),
      "--asr",
      "large-v3",
      "--songs-dir",
      opts.songsDir,
      "--refine",
      join(opts.modelsDir, "aligner"),
      "--spelling",
      "surface",
      "--perturb",
      "--out",
      join(opts.outDir, "large-v3-surface.json"),
    ]);
  });

  test("evaluates with kana spelling", () => {
    const opts = options();
    const kana = pipelineSteps(opts)[3];
    expect(kana?.args).toEqual([
      join(REPO, "eval", "run.ts"),
      "--asr",
      "large-v3",
      "--songs-dir",
      opts.songsDir,
      "--refine",
      join(opts.modelsDir, "aligner"),
      "--spelling",
      "kana",
      "--perturb",
      "--out",
      join(opts.outDir, "large-v3-kana.json"),
    ]);
  });

  test("names the output files after the ASR name", () => {
    const opts = options({ asr: "tuned" });
    const outs = pipelineSteps(opts)
      .slice(2)
      .map((step) => step.args[step.args.indexOf("--out") + 1]);
    expect(outs).toEqual([
      join(opts.outDir, "tuned-surface.json"),
      join(opts.outDir, "tuned-kana.json"),
    ]);
  });

  test("passes each song to every step", () => {
    const steps = pipelineSteps(options({ songs: ["a", "b"] }));
    const tails = steps.map((step) => step.args.slice(-4));
    const songArgs = ["--song", "a", "--song", "b"];
    expect(tails).toEqual([songArgs, songArgs, songArgs, songArgs]);
  });

  test("adds no --song flag without songs", () => {
    const steps = pipelineSteps(options());
    expect(steps.some((step) => step.args.includes("--song"))).toBe(false);
  });
});
