import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { copyFileToClipboard } from "./src/clipboard";
import { pipelineLogPath } from "./src/pipeline-plan";

const logPath = pipelineLogPath(resolve(import.meta.dir, ".."));

async function main(): Promise<void> {
  if (!existsSync(logPath)) {
    throw new Error(`no log at ${logPath}. Run bun run eval:all first`);
  }
  try {
    await copyFileToClipboard(logPath, process.platform);
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(`${reason}; the log is at ${logPath}`);
  }
  process.stderr.write(`Copied ${logPath} to the clipboard\n`);
}

main().catch((error: unknown) => {
  const reason = error instanceof Error ? error.message : String(error);
  process.stderr.write(`error: ${reason}\n`);
  process.exitCode = 1;
});
