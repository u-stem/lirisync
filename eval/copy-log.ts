import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { clipboardCommand } from "./src/clipboard";
import { pipelineLogPath } from "./src/pipeline-plan";

const logPath = pipelineLogPath(resolve(import.meta.dir, ".."));

async function main(): Promise<void> {
  if (!existsSync(logPath)) {
    throw new Error(`no log at ${logPath}. Run bun run eval:all first`);
  }
  const command = clipboardCommand(process.platform, logPath);
  if (command === null) {
    throw new Error(
      `no clipboard command on ${process.platform}; the log is at ${logPath}`,
    );
  }
  const child = Bun.spawn(command.argv, {
    stdin: command.stdin === "file" ? Bun.file(logPath) : "ignore",
    stdout: "inherit",
    stderr: "inherit",
  });
  const exitCode = await child.exited;
  if (exitCode !== 0) {
    throw new Error(
      `${command.argv[0]} failed (exit code ${exitCode}); the log is at ${logPath}`,
    );
  }
  process.stderr.write(`Copied ${logPath} to the clipboard\n`);
}

main().catch((error: unknown) => {
  const reason = error instanceof Error ? error.message : String(error);
  process.stderr.write(`error: ${reason}\n`);
  process.exitCode = 1;
});
