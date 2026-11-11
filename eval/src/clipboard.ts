export type ClipboardCommand = {
  argv: string[];
  /** `file`: the file is fed on stdin. `none`: the command reads it itself. */
  stdin: "file" | "none";
};

/** A PowerShell single-quoted string, in which only `'` needs escaping. */
function powershellQuote(text: string): string {
  return `'${text.replaceAll("'", "''")}'`;
}

/**
 * The command that puts the UTF-8 text file at `path` on the clipboard, or
 * null when the platform has no command we rely on.
 */
export function clipboardCommand(
  platform: NodeJS.Platform,
  path: string,
): ClipboardCommand | null {
  if (platform === "win32") {
    // Read inside PowerShell: piping into clip.exe or Set-Clipboard would
    // decode the bytes with the console code page and garble Japanese.
    return {
      argv: [
        "powershell",
        "-NoProfile",
        "-Command",
        `Get-Content -Raw -Encoding UTF8 -LiteralPath ${powershellQuote(path)} | Set-Clipboard`,
      ],
      stdin: "none",
    };
  }
  if (platform === "darwin") return { argv: ["pbcopy"], stdin: "file" };
  return null;
}

/** Puts the UTF-8 text file at `path` on the clipboard. Throws when it cannot. */
export async function copyFileToClipboard(
  path: string,
  platform: NodeJS.Platform,
): Promise<void> {
  const command = clipboardCommand(platform, path);
  if (command === null) {
    throw new Error(`no clipboard command on ${platform}`);
  }
  const child = Bun.spawn(command.argv, {
    stdin: command.stdin === "file" ? Bun.file(path) : "ignore",
    stdout: "inherit",
    stderr: "inherit",
  });
  const exitCode = await child.exited;
  if (exitCode !== 0) {
    throw new Error(`${command.argv[0]} failed (exit code ${exitCode})`);
  }
}
