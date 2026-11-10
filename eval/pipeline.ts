import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { parseArgs } from "node:util";
import { assertModelFile } from "./src/model-file";
import {
  alignerModelDir,
  type PipelineOptions,
  type PipelineStep,
  parsePipelineOptions,
  pipelineSteps,
  resultPaths,
  separatorModelPath,
} from "./src/pipeline-plan";
import { assertAlignerModelDir } from "./src/refine-options";
import { listSongs, selectSongs } from "./src/song-set";

const repoRoot = resolve(import.meta.dir, "..");

function log(text: string): void {
  process.stderr.write(text);
}

/** Checks the inputs of every step, so a wrong path fails before hours of work. */
async function assertReady(options: PipelineOptions): Promise<void> {
  // Transcription runs on uv after separation, which takes long; check it now.
  if (Bun.which("uv") === null) {
    throw new Error(
      "uv was not found on PATH. Run scripts/setup-windows.ps1 or install uv (see README.md)",
    );
  }
  await assertModelFile(separatorModelPath(options.modelsDir));
  await assertAlignerModelDir(alignerModelDir(options.modelsDir));
  const slugs = await listSongs(options.songsDir).catch((error: unknown) => {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(
      `${reason}. See "曲の置き方" in eval/README.md for how to put songs in`,
    );
  });
  selectSongs(slugs, options.songs);
}

async function runStep(
  step: PipelineStep,
  index: number,
  total: number,
  cwd: string,
): Promise<void> {
  log(`==> [${index}/${total}] ${step.name}\n`);
  // The steps run on the same bun as this command, not whichever is on PATH.
  const command = step.command === "bun" ? process.execPath : step.command;
  const child = Bun.spawn([command, ...step.args], {
    cwd,
    stdin: "inherit",
    stdout: "inherit",
    stderr: "inherit",
  });
  const exitCode = await child.exited;
  if (exitCode !== 0) {
    throw new Error(
      `${step.name} failed (exit code ${exitCode}). Run the same command again to continue: finished songs are skipped in separate and transcribe`,
    );
  }
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      "models-dir": { type: "string" },
      "asr-model": { type: "string" },
      asr: { type: "string" },
      "out-dir": { type: "string" },
      "songs-dir": { type: "string" },
      song: { type: "string", multiple: true },
    },
    strict: true,
  });
  const options = parsePipelineOptions(values, process.platform, repoRoot);
  await assertReady(options);
  await mkdir(options.outDir, { recursive: true });

  const steps = pipelineSteps(options);
  for (const [i, step] of steps.entries()) {
    await runStep(step, i + 1, steps.length, repoRoot);
  }
  log("Wrote:\n");
  for (const path of resultPaths(options)) {
    log(`  ${path}\n`);
  }
}

main().catch((error: unknown) => {
  const reason = error instanceof Error ? error.message : String(error);
  process.stderr.write(`error: ${reason}\n`);
  process.exitCode = 1;
});
