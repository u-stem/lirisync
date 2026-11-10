import { join, resolve } from "node:path";
import { Ms, parseMs } from "@lirisync/core";
import { assertModelFile } from "./model-file";

export type RefineOptions = {
  /** Absolute path of the forced-alignment model directory. */
  modelDir: string;
  spelling: "surface" | "kana";
  /** Room the worker adds around each window. */
  margin: Ms;
};

/** Files the worker reads from the model directory. */
const MODEL_FILES: readonly string[] = ["model.int8.onnx", "vocab.json"];

const DEFAULT_MARGIN_MS = 1000;

/** The raw values of the stage-2 flags, as `parseArgs` gives them. */
export type RefineFlags = {
  refine?: string;
  spelling?: string;
  "margin-ms"?: string;
};

function parseSpelling(text: string): "surface" | "kana" {
  if (text === "surface" || text === "kana") return text;
  throw new Error(
    `--spelling must be "surface" or "kana", not ${JSON.stringify(text)}`,
  );
}

function parseMargin(text: string): Ms {
  const parsed = /^\d+$/.test(text) ? Number(text) : Number.NaN;
  const margin = Ms.safeParse(parsed);
  if (!margin.success) {
    throw new Error(
      `--margin-ms must be an integer of 0 or more, not ${JSON.stringify(text)}`,
    );
  }
  return margin.data;
}

/**
 * Reads the stage-2 flags. `null` when `--refine` is absent; then `--spelling`
 * and `--margin-ms` are errors, since they would silently do nothing.
 */
export function parseRefineOptions(flags: RefineFlags): RefineOptions | null {
  const { refine, spelling, "margin-ms": margin } = flags;
  if (refine === undefined) {
    if (spelling !== undefined) throw new Error("--spelling needs --refine");
    if (margin !== undefined) throw new Error("--margin-ms needs --refine");
    return null;
  }
  if (refine === "") {
    throw new Error("--refine needs the model directory");
  }
  return {
    modelDir: resolve(refine),
    spelling: spelling === undefined ? "surface" : parseSpelling(spelling),
    margin:
      margin === undefined ? parseMs(DEFAULT_MARGIN_MS) : parseMargin(margin),
  };
}

/** Throws unless `modelDir` holds the files the worker reads. */
export async function assertAlignerModelDir(modelDir: string): Promise<void> {
  for (const name of MODEL_FILES) {
    await assertModelFile(join(modelDir, name));
  }
}
