import { rm, writeFile } from "node:fs/promises";
import { WorkerProtocolError } from "../adapters/worker-client";
import {
  type Progress,
  type SeparateParams,
  SeparateResult,
} from "../adapters/worker-protocol";
import { formatMeta, type SongPlan } from "./separation-plan";
import { createProgressReporter, formatClock } from "./separation-progress";

/** Sends one `separate` request and resolves with the raw result. */
export type SeparateRequest = (
  params: SeparateParams,
  onProgress: (progress: Progress) => void,
) => Promise<Record<string, unknown>>;

export type SeparationModel = {
  /** Absolute path, passed to the worker. */
  path: string;
  /** File name, recorded in the metadata. */
  name: string;
  sha256: string;
};

export type SeparationDeps = {
  request: SeparateRequest;
  /** Where progress and log lines go: stderr. */
  write: (text: string) => void;
  tty: boolean;
  /** Milliseconds from a monotonic clock. */
  now: () => number;
};

const MS_PER_SECOND = 1000;

async function separateOne(
  plan: Extract<SongPlan, { kind: "separate" }>,
  position: { index: number; total: number },
  model: SeparationModel,
  worker: string,
  deps: SeparationDeps,
): Promise<void> {
  // Metadata first and audio last, like lirisync-transcribe: the existence of
  // the audio means that the song is finished. Vocals being replaced go first,
  // so a failure never leaves the new metadata beside the old audio.
  await rm(plan.output, { force: true });
  await writeFile(
    plan.metaPath,
    formatMeta({
      input: plan.inputName,
      model: model.name,
      modelSha256: model.sha256,
      worker,
    }),
  );
  const progress = createProgressReporter({
    slug: plan.slug,
    ...position,
    tty: deps.tty,
    write: deps.write,
  });
  const started = deps.now();
  let raw: Record<string, unknown>;
  try {
    raw = await deps.request(
      { input: plan.input, output: plan.output, model: model.path },
      (update) => progress.update(update),
    );
  } finally {
    progress.finish();
  }
  const parsed = SeparateResult.safeParse(raw);
  if (!parsed.success) {
    throw new WorkerProtocolError(
      `The separate result is not usable: ${parsed.error.message}`,
    );
  }
  const seconds = ((deps.now() - started) / MS_PER_SECOND).toFixed(1);
  deps.write(
    `[${position.index}/${position.total}] ${plan.slug}: ${formatClock(parsed.data.durationMs)} separated in ${seconds} s\n`,
  );
}

/**
 * Runs the plans in order. A failure is rethrown with the slug in front and
 * a hint that `--skip-existing` resumes after the songs that are done.
 */
export async function separateSongs(
  plans: readonly SongPlan[],
  model: SeparationModel,
  worker: string,
  deps: SeparationDeps,
): Promise<void> {
  const total = plans.length;
  for (const [offset, plan] of plans.entries()) {
    const position = { index: offset + 1, total };
    if (plan.kind === "skip") {
      deps.write(
        `[${position.index}/${total}] ${plan.slug}: skipped, audio/${plan.existing} exists\n`,
      );
      continue;
    }
    try {
      await separateOne(plan, position, model, worker, deps);
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      throw new Error(
        `${plan.slug}: ${reason} (run again with --skip-existing to continue after the finished songs)`,
      );
    }
  }
}
