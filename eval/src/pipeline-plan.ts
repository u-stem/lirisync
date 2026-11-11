import { join, resolve } from "node:path";
import { assertAsrName } from "./song-set";

/** Where the setup script puts the models on a Windows machine. */
const WINDOWS_MODELS_DIR = "C:\\lirisync-models";
const DEFAULT_ASR_MODEL = "Systran/faster-whisper-large-v3";
const DEFAULT_ASR_NAME = "large-v3";

/** The raw values of the pipeline flags, as `parseArgs` gives them. */
export type PipelineFlags = {
  "models-dir"?: string;
  "asr-model"?: string;
  asr?: string;
  "out-dir"?: string;
  "songs-dir"?: string;
  song?: string[];
};

export type PipelineOptions = {
  /** Directory holding `separator/` and `aligner/`. */
  modelsDir: string;
  /** Hugging Face repo id or local path of the Whisper model. */
  asrModel: string;
  /** Name under which the transcripts are written and read. */
  asr: string;
  outDir: string;
  songsDir: string;
  /** Slugs to process; undefined means every song. */
  songs: string[] | undefined;
  repoRoot: string;
};

export type PipelineStep = {
  name: string;
  command: string;
  args: string[];
};

/** `value`, unless it is empty: `resolve("")` would quietly be the current directory. */
function nonEmpty(value: string, message: string): string {
  if (value === "") throw new Error(message);
  return value;
}

/** A given directory made absolute, or `fallback`. */
function directoryOf(
  flag: string | undefined,
  name: string,
  fallback: string,
): string {
  if (flag === undefined) return fallback;
  return resolve(nonEmpty(flag, `${name} needs a directory`));
}

function modelsDirOf(
  flag: string | undefined,
  platform: NodeJS.Platform,
): string {
  if (flag !== undefined) {
    return resolve(nonEmpty(flag, "--models-dir needs a directory"));
  }
  // The default is a Windows path; resolving it elsewhere would glue it to
  // the current directory.
  if (platform === "win32") return WINDOWS_MODELS_DIR;
  throw new Error("--models-dir is required outside Windows");
}

/** Checks the flags and fills the defaults. Paths come out absolute. */
export function parsePipelineOptions(
  flags: PipelineFlags,
  platform: NodeJS.Platform,
  repoRoot: string,
): PipelineOptions {
  const asr = flags.asr ?? DEFAULT_ASR_NAME;
  assertAsrName(asr);
  return {
    modelsDir: modelsDirOf(flags["models-dir"], platform),
    asrModel: nonEmpty(
      flags["asr-model"] ?? DEFAULT_ASR_MODEL,
      "--asr-model needs a model",
    ),
    asr,
    outDir: directoryOf(
      flags["out-dir"],
      "--out-dir",
      join(repoRoot, "eval", "results"),
    ),
    songsDir: directoryOf(
      flags["songs-dir"],
      "--songs-dir",
      join(repoRoot, "eval", "songs"),
    ),
    songs: flags.song,
    repoRoot,
  };
}

/** Where `eval:all` writes everything it and its steps print. */
export function pipelineLogPath(repoRoot: string): string {
  return join(repoRoot, "eval", "logs", "eval-all.log");
}

/** Set for the steps unless the caller already set them. */
const STEP_ENV_DEFAULTS = {
  // Piped Python output would otherwise use the Windows code page, which the
  // log, read as UTF-8, would garble.
  PYTHONUTF8: "1",
  // Piped stdout is block-buffered otherwise, so output would show up late
  // and be lost from the log when a step is killed.
  PYTHONUNBUFFERED: "1",
  // Windows without developer mode cannot make the cache's symlinks; the
  // cache still works, and the warning only buries the real output.
  HF_HUB_DISABLE_SYMLINKS_WARNING: "1",
};

/** The environment of the steps: `base` with the step defaults filled in. */
export function stepEnv(
  base: Readonly<Record<string, string | undefined>>,
): Record<string, string | undefined> {
  return { ...STEP_ENV_DEFAULTS, ...base };
}

/** The first lines of the log, so a pasted log says what ran where. */
export function logHeader(
  args: readonly string[],
  platform: NodeJS.Platform,
  startedAt: Date,
): string {
  // Quoted the way a shell would take it back, so a pasted log shows where
  // an argument with a space ends.
  const shown = args.map((arg) =>
    /\s/.test(arg) ? `"${arg.replaceAll('"', '\\"')}"` : arg,
  );
  const command = ["bun run eval:all", ...shown].join(" ");
  return `# ${command}\n# started ${startedAt.toISOString()} on ${platform}\n`;
}

/** Where the separation model sits under the models directory. */
export function separatorModelPath(modelsDir: string): string {
  return join(modelsDir, "separator", "sep-all-int8.onnx");
}

/** Where the aligner model directory sits under the models directory. */
export function alignerModelDir(modelsDir: string): string {
  return join(modelsDir, "aligner");
}

/** The two result files `steps` write, in the order the steps run. */
export function resultPaths(options: PipelineOptions): [string, string] {
  return [
    join(options.outDir, `${options.asr}-surface.json`),
    join(options.outDir, `${options.asr}-kana.json`),
  ];
}

/**
 * The commands to run, in order. Every path is absolute, so the steps do not
 * depend on the directory they start in.
 */
export function pipelineSteps(options: PipelineOptions): PipelineStep[] {
  const songFlags = (options.songs ?? []).flatMap((slug) => ["--song", slug]);
  const [surfaceOut, kanaOut] = resultPaths(options);
  const evalArgs = (spelling: string, out: string): string[] => [
    join(options.repoRoot, "eval", "run.ts"),
    "--asr",
    options.asr,
    "--songs-dir",
    options.songsDir,
    "--refine",
    alignerModelDir(options.modelsDir),
    "--spelling",
    spelling,
    "--perturb",
    "--out",
    out,
    ...songFlags,
  ];
  return [
    {
      name: "separate",
      command: "bun",
      args: [
        join(options.repoRoot, "eval", "separate.ts"),
        "--model",
        separatorModelPath(options.modelsDir),
        "--songs-dir",
        options.songsDir,
        "--skip-existing",
        ...songFlags,
      ],
    },
    {
      name: "transcribe",
      command: "uv",
      args: [
        "--directory",
        join(options.repoRoot, "eval", "transcribe"),
        "run",
        "lirisync-transcribe",
        "--model",
        options.asrModel,
        "--name",
        options.asr,
        "--songs-dir",
        options.songsDir,
        "--skip-existing",
        ...songFlags,
      ],
    },
    {
      name: "eval surface",
      command: "bun",
      args: evalArgs("surface", surfaceOut),
    },
    { name: "eval kana", command: "bun", args: evalArgs("kana", kanaOut) },
  ];
}
