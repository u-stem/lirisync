import { basename, join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { alignWorkerCommand, startWorker } from "./adapters/worker-process";
import { assertModelFile, sha256File } from "./src/model-file";
import {
  assertPlanOptions,
  type PlanOptions,
  planSong,
} from "./src/separation-plan";
import { separateSongs } from "./src/separation-run";
import { listSongs, selectSongs } from "./src/song-set";

const repoRoot = resolve(import.meta.dir, "..");

function log(text: string): void {
  process.stderr.write(text);
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      model: { type: "string" },
      "songs-dir": {
        type: "string",
        default: join(repoRoot, "eval", "songs"),
      },
      song: { type: "string", multiple: true },
      input: { type: "string", default: "mix" },
      overwrite: { type: "boolean", default: false },
      "skip-existing": { type: "boolean", default: false },
    },
    strict: true,
  });
  if (values.model === undefined) {
    throw new Error("--model <path> is required");
  }
  const options: PlanOptions = {
    inputStem: values.input,
    overwrite: values.overwrite,
    skipExisting: values["skip-existing"],
  };
  assertPlanOptions(options);

  // Check everything before the worker starts and the model is hashed, so a
  // wrong path or a conflicting file fails in a moment, not after minutes.
  const modelPath = resolve(values.model);
  await assertModelFile(modelPath);
  const songsDir = resolve(values["songs-dir"]);
  const slugs = selectSongs(await listSongs(songsDir), values.song);
  const plans = [];
  for (const slug of slugs) {
    plans.push(await planSong(songsDir, slug, options));
  }

  log(`Hashing ${basename(modelPath)}\n`);
  const model = {
    path: modelPath,
    name: basename(modelPath),
    sha256: await sha256File(modelPath),
  };

  const worker = await startWorker(alignWorkerCommand(repoRoot), ["separate"]);
  try {
    await separateSongs(plans, model, worker.hello.worker, {
      request: (params, onProgress) =>
        worker.client.request("separate", params, { onProgress }),
      write: log,
      tty: process.stderr.isTTY === true,
      now: () => performance.now(),
    });
  } finally {
    const exitCode = await worker.stop();
    if (exitCode !== 0) {
      process.stderr.write(
        `warning: the worker exited with code ${exitCode}\n`,
      );
      process.exitCode = 1;
    }
  }
}

main().catch((error: unknown) => {
  const reason = error instanceof Error ? error.message : String(error);
  process.stderr.write(`error: ${reason}\n`);
  process.exitCode = 1;
});
