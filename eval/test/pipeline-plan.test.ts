import { describe, expect, test } from "bun:test";
import { join, resolve } from "node:path";
import {
  cudaLibraryDirs,
  logHeader,
  type PipelineOptions,
  parsePipelineOptions,
  pipelineLogPath,
  pipelineSteps,
  prependPath,
  shouldCopyLog,
  stepEnv,
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
    device: undefined,
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

  test("rejects an empty ASR model", () => {
    expect(() =>
      parsePipelineOptions({ "asr-model": "" }, "win32", REPO),
    ).toThrow("--asr-model");
  });

  test("rejects an empty output directory", () => {
    expect(() =>
      parsePipelineOptions({ "out-dir": "" }, "win32", REPO),
    ).toThrow("--out-dir");
  });

  test("rejects an empty songs directory", () => {
    expect(() =>
      parsePipelineOptions({ "songs-dir": "" }, "win32", REPO),
    ).toThrow("--songs-dir");
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

  test("leaves the device unset by default", () => {
    const parsed = parsePipelineOptions({}, "win32", REPO);
    expect(parsed.device).toBeUndefined();
  });

  test("keeps a given device", () => {
    const parsed = parsePipelineOptions({ device: "cpu" }, "win32", REPO);
    expect(parsed.device).toBe("cpu");
  });

  test("rejects an unknown device", () => {
    expect(() =>
      parsePipelineOptions({ device: "gpu" }, "win32", REPO),
    ).toThrow("--device must be auto, cpu or cuda");
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

  test("passes a given device to transcribe", () => {
    const transcribe = pipelineSteps(options({ device: "cpu" }))[1];
    expect(transcribe?.args.slice(-2)).toEqual(["--device", "cpu"]);
  });

  test("adds no --device flag without a device", () => {
    const steps = pipelineSteps(options());
    expect(steps.some((step) => step.args.includes("--device"))).toBe(false);
  });

  test("puts the CUDA libraries on PATH for transcribe", () => {
    const opts = options();
    const transcribe = pipelineSteps(opts)[1];
    expect(transcribe?.pathPrepend).toEqual(cudaLibraryDirs(opts.modelsDir));
  });

  test("marks only the eval steps as needing lyrics and labels", () => {
    const flags = pipelineSteps(options()).map((step) => step.needsLabels);
    expect(flags).toEqual([false, false, true, true]);
  });

  test("puts nothing on PATH for the other steps", () => {
    const steps = pipelineSteps(options());
    const others = [steps[0], steps[2], steps[3]];
    expect(others.map((step) => step?.pathPrepend)).toEqual([[], [], []]);
  });

  test("adds no --song flag without songs", () => {
    const steps = pipelineSteps(options());
    expect(steps.some((step) => step.args.includes("--song"))).toBe(false);
  });
});

describe("pipelineLogPath", () => {
  test("puts the log under eval/logs", () => {
    expect(pipelineLogPath(REPO)).toBe(
      join(REPO, "eval", "logs", "eval-all.log"),
    );
  });
});

describe("stepEnv", () => {
  test("keeps the given variables", () => {
    const env = stepEnv({ PATH: "/bin" });
    expect(env.PATH).toBe("/bin");
  });

  test("makes Python write UTF-8", () => {
    const env = stepEnv({});
    expect(env.PYTHONUTF8).toBe("1");
  });

  test("keeps Python output unbuffered", () => {
    const env = stepEnv({});
    expect(env.PYTHONUNBUFFERED).toBe("1");
  });

  test("silences the symlink warning", () => {
    const env = stepEnv({});
    expect(env.HF_HUB_DISABLE_SYMLINKS_WARNING).toBe("1");
  });

  test("lets a set variable win over the default", () => {
    const env = stepEnv({ PYTHONUTF8: "0" });
    expect(env.PYTHONUTF8).toBe("0");
  });
});

describe("logHeader", () => {
  test("names the arguments, the start and the platform", () => {
    const header = logHeader(
      ["--song", "a"],
      "win32",
      new Date("2026-11-11T01:02:03.000Z"),
    );
    expect(header).toBe(
      "# bun run eval:all --song a\n# started 2026-11-11T01:02:03.000Z on win32\n",
    );
  });

  test("quotes an argument with a space", () => {
    const header = logHeader(
      ["--songs-dir", "C:\\My Songs"],
      "win32",
      new Date("2026-11-11T01:02:03.000Z"),
    );
    expect(header.split("\n")[0]).toBe(
      '# bun run eval:all --songs-dir "C:\\My Songs"',
    );
  });
});

describe("shouldCopyLog", () => {
  test("copies after a run in a terminal", () => {
    expect(shouldCopyLog({ noCopyLog: false, interactive: true })).toBe(true);
  });

  test("does not copy when asked not to", () => {
    expect(shouldCopyLog({ noCopyLog: true, interactive: true })).toBe(false);
  });

  test("does not copy outside a terminal", () => {
    expect(shouldCopyLog({ noCopyLog: false, interactive: false })).toBe(false);
  });
});

describe("cudaLibraryDirs", () => {
  test("lists the bin directories of the NVIDIA wheels", () => {
    const models = resolve("models");
    expect(cudaLibraryDirs(models)).toEqual([
      join(models, "cuda", "nvidia", "cublas", "bin"),
      join(models, "cuda", "nvidia", "cudnn", "bin"),
      join(models, "cuda", "nvidia", "cuda_nvrtc", "bin"),
    ]);
  });
});

describe("prependPath", () => {
  test("puts the directories before the existing entries", () => {
    const env = prependPath({ PATH: "/bin" }, ["/a", "/b"], ":");
    expect(env.PATH).toBe("/a:/b:/bin");
  });

  test("keeps the spelling of the existing key", () => {
    const env = prependPath({ Path: "C:\\bin" }, ["C:\\a"], ";");
    expect(env).toEqual({ Path: "C:\\a;C:\\bin" });
  });

  test("folds other spellings of the key into one", () => {
    const env = prependPath({ Path: "C:\\x", PATH: "C:\\y" }, ["C:\\a"], ";");
    expect(env).toEqual({ Path: "C:\\a;C:\\x" });
  });

  test("creates PATH when there is none", () => {
    const env = prependPath({ HOME: "/h" }, ["/a"], ":");
    expect(env).toEqual({ HOME: "/h", PATH: "/a" });
  });

  test("leaves the environment as it is without directories", () => {
    const env = prependPath({ PATH: "/bin" }, [], ":");
    expect(env).toEqual({ PATH: "/bin" });
  });
});
