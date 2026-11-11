import { existsSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { delimiter, join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { copyFileToClipboard, hasClipboardCommand } from "./src/clipboard";
import { assertModelFile } from "./src/model-file";
import {
  alignerModelDir,
  logHeader,
  type PipelineOptions,
  type PipelineStep,
  parsePipelineOptions,
  pipelineLogPath,
  pipelineSteps,
  prependPath,
  resultPaths,
  separatorModelPath,
  shouldCopyLog,
  stepEnv,
} from "./src/pipeline-plan";
import { assertAlignerModelDir } from "./src/refine-options";
import { openRunLog } from "./src/run-log";
import { checkSongFiles, listSongFiles } from "./src/song-files";
import { listSongs, selectSongs } from "./src/song-set";
import { teeStream } from "./src/tee";

const repoRoot = resolve(import.meta.dir, "..");

/** Everything shown is also written here, so the run can be shared whole. */
const runLog = openRunLog(pipelineLogPath(repoRoot), (message) =>
  process.stderr.write(`warning: ${message}\n`),
);

/** Set once the flags are read; a run that fails before that is not copied. */
let copyLog = false;

function toLog(chunk: string | Uint8Array): void {
  runLog.write(chunk);
}

function log(text: string): void {
  process.stderr.write(text);
  toLog(text);
}

/**
 * Lists what each song lacks. Throws when a song cannot be separated; returns
 * whether every song has what the eval steps read.
 */
async function checkSongs(
  songsDir: string,
  slugs: readonly string[],
): Promise<boolean> {
  log("==> Checking songs\n");
  let blocked = false;
  let labelsReady = true;
  for (const slug of slugs) {
    const problems = checkSongFiles(await listSongFiles(join(songsDir, slug)));
    if (problems.length === 0) log(`    ${slug}: ok\n`);
    for (const problem of problems) {
      const hint = problem.hint === null ? "" : ` (${problem.hint})`;
      log(`    ${slug}: no ${problem.file}${hint}\n`);
      if (problem.blocking) blocked = true;
      else labelsReady = false;
    }
  }
  if (blocked) {
    throw new Error(
      `cannot separate the songs above. See "曲の置き方" in eval/README.md, or add songs with bun run eval:add-song`,
    );
  }
  if (!labelsReady) {
    log(
      "    Separation and transcription run now; the eval steps wait for the files above\n",
    );
  }
  return labelsReady;
}

/**
 * Checks the inputs of every step, so a wrong path fails before hours of work.
 * Returns whether the eval steps can run.
 */
async function assertReady(options: PipelineOptions): Promise<boolean> {
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
  return checkSongs(options.songsDir, selectSongs(slugs, options.songs));
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
  const extraPath = step.pathPrepend.filter((dir) => existsSync(dir));
  for (const dir of extraPath) log(`    PATH += ${dir}\n`);
  const child = Bun.spawn([command, ...step.args], {
    cwd,
    env: prependPath(stepEnv(process.env), extraPath, delimiter),
    stdin: "inherit",
    stdout: "pipe",
    stderr: "pipe",
  });
  const relayed = Promise.all([
    teeStream(child.stdout, [(chunk) => process.stdout.write(chunk), toLog]),
    teeStream(child.stderr, [(chunk) => process.stderr.write(chunk), toLog]),
  ]).catch((error: unknown) => {
    // Nothing reads the step's output any more; do not leave it running.
    child.kill();
    throw error;
  });
  const [, exitCode] = await Promise.all([relayed, child.exited]);
  if (exitCode !== 0) {
    throw new Error(
      `${step.name} failed (exit code ${exitCode}). Run the same command again to continue: finished songs are skipped in separate and transcribe`,
    );
  }
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  toLog(logHeader(args, process.platform, new Date()));
  const { values } = parseArgs({
    args,
    options: {
      "models-dir": { type: "string" },
      "asr-model": { type: "string" },
      asr: { type: "string" },
      "out-dir": { type: "string" },
      "songs-dir": { type: "string" },
      song: { type: "string", multiple: true },
      device: { type: "string" },
      "no-copy-log": { type: "boolean", default: false },
    },
    strict: true,
  });
  copyLog = shouldCopyLog({
    noCopyLog: values["no-copy-log"],
    interactive: process.stderr.isTTY === true,
    supported: hasClipboardCommand(process.platform),
  });
  const options = parsePipelineOptions(values, process.platform, repoRoot);
  const labelsReady = await assertReady(options);
  await mkdir(options.outDir, { recursive: true });

  const steps = pipelineSteps(options);
  for (const [i, step] of steps.entries()) {
    if (step.needsLabels && !labelsReady) {
      throw new Error(
        "separated and transcribed; the eval steps need lyrics.txt and labels.txt in every song (listed under Checking songs). Add them and run again",
      );
    }
    await runStep(step, i + 1, steps.length, repoRoot);
  }
  log("Wrote:\n");
  for (const path of resultPaths(options)) {
    log(`  ${path}\n`);
  }
}

main()
  .catch((error: unknown) => {
    const reason = error instanceof Error ? error.message : String(error);
    log(`error: ${reason}\n`);
    process.exitCode = 1;
  })
  .finally(async () => {
    const path = runLog.path;
    if (path !== null) log(`Log: ${path}\n`);
    runLog.close();
    if (path === null) return;
    if (!copyLog) {
      // eval:log would fail the same way where there is no clipboard command.
      if (hasClipboardCommand(process.platform)) {
        process.stderr.write(
          "Copy it to the clipboard with: bun run eval:log\n",
        );
      }
      return;
    }
    try {
      await copyFileToClipboard(path, process.platform);
      process.stderr.write("Copied the log to the clipboard\n");
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      process.stderr.write(
        `warning: could not copy the log (${reason}); run bun run eval:log\n`,
      );
    }
  });
