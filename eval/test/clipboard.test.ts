import { describe, expect, test } from "bun:test";
import { clipboardCommand, hasClipboardCommand } from "../src/clipboard";

describe("hasClipboardCommand", () => {
  test("is true on win32", () => {
    expect(hasClipboardCommand("win32")).toBe(true);
  });

  test("is false on linux", () => {
    expect(hasClipboardCommand("linux")).toBe(false);
  });
});

describe("clipboardCommand", () => {
  test("reads the file in PowerShell on win32", () => {
    const command = clipboardCommand("win32", "C:\\repo\\eval\\logs\\a.log");
    expect(command).toEqual({
      argv: [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-Content -Raw -Encoding UTF8 -LiteralPath 'C:\\repo\\eval\\logs\\a.log' | Set-Clipboard",
      ],
      stdin: "none",
    });
  });

  test("doubles single quotes in the path on win32", () => {
    const command = clipboardCommand("win32", "C:\\it's\\a.log");
    expect(command?.argv[3]).toBe(
      "Get-Content -Raw -Encoding UTF8 -LiteralPath 'C:\\it''s\\a.log' | Set-Clipboard",
    );
  });

  test("feeds the file to pbcopy on darwin", () => {
    const command = clipboardCommand("darwin", "/repo/eval/logs/a.log");
    expect(command).toEqual({ argv: ["pbcopy"], stdin: "file" });
  });

  test("has no command elsewhere", () => {
    const command = clipboardCommand("linux", "/repo/eval/logs/a.log");
    expect(command).toBeNull();
  });
});
