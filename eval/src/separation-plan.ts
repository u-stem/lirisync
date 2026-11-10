import { join } from "node:path";
import {
  listFiles,
  pickByStem,
  sameName,
  VOCALS_STEM,
  withStem,
} from "./audio-files";

export type PlanOptions = {
  /** Stem of the source file `audio/<stem>.*`. */
  inputStem: string;
  overwrite: boolean;
  skipExisting: boolean;
};

export type SongPlan =
  | { kind: "skip"; slug: string; existing: string }
  | {
      kind: "separate";
      slug: string;
      /** Absolute path of the source audio. */
      input: string;
      inputName: string;
      /** Absolute path of the vocals WAV to write. */
      output: string;
      /** Absolute path of the metadata file, written before the audio. */
      metaPath: string;
    };

/** What `vocals.meta.json` records. Keys are camelCase on disk. */
export type SeparationMeta = {
  input: string;
  model: string;
  modelSha256: string;
  worker: string;
};

function isWav(name: string): boolean {
  return name.toLowerCase().endsWith(".wav");
}

/** Throws on options that cannot work together, before any file is read. */
export function assertPlanOptions(options: PlanOptions): void {
  if (options.overwrite && options.skipExisting) {
    throw new Error("--overwrite and --skip-existing cannot be used together");
  }
  if (sameName(options.inputStem, VOCALS_STEM)) {
    throw new Error(
      `--input ${JSON.stringify(options.inputStem)} is the name of the output; use the stem of the mix`,
    );
  }
}

/** Decides what to do with one song, from the files in its `audio/`. */
async function decide(
  songsDir: string,
  slug: string,
  options: PlanOptions,
): Promise<SongPlan> {
  const audioDir = join(songsDir, slug, "audio");
  const files = await listFiles(audioDir);
  const existing = withStem(files, VOCALS_STEM);
  const [current] = existing;
  if (current !== undefined && options.skipExisting) {
    return { kind: "skip", slug, existing: current };
  }
  const inputName = pickByStem(files, options.inputStem);
  let outputName = `${VOCALS_STEM}.wav`;
  if (current !== undefined) {
    if (existing.length > 1) {
      throw new Error(
        `more than one audio/${VOCALS_STEM}.* file: ${existing.join(", ")}; the transcriber needs exactly one`,
      );
    }
    if (!isWav(current)) {
      throw new Error(
        `audio/${current} is not a .wav; it is not replaced, and a second vocals file would confuse the transcriber. Move it away first`,
      );
    }
    if (!options.overwrite) {
      throw new Error(
        `audio/${current} exists; use --overwrite to replace it or --skip-existing to leave it`,
      );
    }
    // The file's own spelling, so a case-sensitive disk is not left with two.
    outputName = current;
  }
  return {
    kind: "separate",
    slug,
    input: join(audioDir, inputName),
    inputName,
    output: join(audioDir, outputName),
    metaPath: join(audioDir, `${VOCALS_STEM}.meta.json`),
  };
}

/**
 * Plans the separation of one song. Every failure is rethrown with the slug
 * in front, like `loadSong`.
 */
export async function planSong(
  songsDir: string,
  slug: string,
  options: PlanOptions,
): Promise<SongPlan> {
  try {
    return await decide(songsDir, slug, options);
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(`${slug}: ${reason}`);
  }
}

export function formatMeta(meta: SeparationMeta): string {
  return `${JSON.stringify(meta, null, 2)}\n`;
}
