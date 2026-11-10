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

function modelsDirOf(
  flag: string | undefined,
  platform: NodeJS.Platform,
): string {
  if (flag !== undefined) {
    if (flag === "") throw new Error("--models-dir needs a directory");
    return resolve(flag);
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
    asrModel: flags["asr-model"] ?? DEFAULT_ASR_MODEL,
    asr,
    outDir:
      flags["out-dir"] === undefined
        ? join(repoRoot, "eval", "results")
        : resolve(flags["out-dir"]),
    songsDir:
      flags["songs-dir"] === undefined
        ? join(repoRoot, "eval", "songs")
        : resolve(flags["songs-dir"]),
    songs: flags.song,
    repoRoot,
  };
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
