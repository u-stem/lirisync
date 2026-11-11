import { describe, expect, test } from "bun:test";
import { parseMs } from "@lirisync/core";
import {
  decodeExoText,
  exoLabels,
  formatAudacityLabels,
  parseExo,
} from "../src/exo-labels";
import { parseAudacityLabels } from "../src/labels";

/** `text` as ExEdit stores it: UTF-16LE in hex, padded with zeros. */
function hexText(text: string): string {
  let hex = "";
  for (const unit of text) {
    const code = unit.charCodeAt(0);
    hex += (code & 0xff).toString(16).padStart(2, "0");
    hex += (code >> 8).toString(16).padStart(2, "0");
  }
  return hex.padEnd(4096, "0");
}

type Obj =
  | { kind: "audio"; start: number; position?: string; speed?: string }
  | { kind: "text"; start: number; text: string };

function exo(objects: Obj[], rate = 60, scale = 1): string {
  const lines = [
    "[exedit]",
    "width=1920",
    "height=1080",
    `rate=${rate}`,
    `scale=${scale}`,
    "length=7440",
  ];
  objects.forEach((obj, index) => {
    lines.push(`[${index}]`, `start=${obj.start}`, `end=${obj.start + 100}`);
    if (obj.kind === "audio") {
      lines.push(
        "layer=1",
        "audio=1",
        `[${index}.0]`,
        "_name=音声ファイル",
        `再生位置=${obj.position ?? "0.00"}`,
        `再生速度=${obj.speed ?? "100.0"}`,
        "file=D:\\songs\\song01\\audio\\mix.wav",
        `[${index}.1]`,
        "_name=標準再生",
      );
    } else {
      lines.push(
        "layer=2",
        "camera=0",
        `[${index}.0]`,
        "_name=テキスト",
        "font=MS UI Gothic",
        `text=${hexText(obj.text)}`,
        `[${index}.1]`,
        "_name=標準描画",
      );
    }
  });
  return `${lines.join("\r\n")}\r\n`;
}

const AUDIO: Obj = { kind: "audio", start: parseMs(61) };

function labelsOf(objects: Obj[], rate?: number, scale?: number) {
  return exoLabels(parseExo(exo(objects, rate, scale)));
}

describe("decodeExoText", () => {
  test("reads UTF-16LE hex up to the first zero unit", () => {
    expect(decodeExoText(hexText("12"))).toBe("12");
  });

  test("reads characters outside ASCII", () => {
    expect(decodeExoText(hexText("歌"))).toBe("歌");
  });

  test("rejects text that is not hex", () => {
    expect(() => decodeExoText("zz00")).toThrow("not UTF-16LE hex");
  });

  test("rejects an odd number of bytes", () => {
    expect(() => decodeExoText("310")).toThrow("not UTF-16LE hex");
  });
});

describe("exoLabels", () => {
  test("measures each text from the start of the audio", () => {
    const labels = labelsOf([
      AUDIO,
      { kind: "text", start: 271, text: "1" },
      { kind: "text", start: 1381, text: "2" },
      { kind: "text", start: 3741, text: "3" },
    ]);
    expect(labels).toEqual([
      { line: 1, start: parseMs(3500) },
      { line: 2, start: parseMs(22000) },
      { line: 3, start: parseMs(61333) },
    ]);
  });

  test("rounds half a millisecond up", () => {
    // 1 frame at 8 fps is 125 ms; at scale 1 and rate 16 it is 62.5 ms.
    const labels = labelsOf(
      [
        { kind: "audio", start: parseMs(1) },
        { kind: "text", start: 2, text: "1" },
      ],
      16,
    );
    expect(labels).toEqual([{ line: 1, start: parseMs(63) }]);
  });

  test("uses the scale of the frame rate", () => {
    // 30000/1001 fps: 30 frames are 1001 ms.
    const labels = labelsOf(
      [
        { kind: "audio", start: parseMs(1) },
        { kind: "text", start: 31, text: "1" },
      ],
      30000,
      1001,
    );
    expect(labels).toEqual([{ line: 1, start: parseMs(1001) }]);
  });

  test("adds the play position of the audio", () => {
    const labels = labelsOf([
      { kind: "audio", start: 61, position: "2.50" },
      { kind: "text", start: 121, text: "1" },
    ]);
    expect(labels).toEqual([{ line: 1, start: parseMs(3500) }]);
  });

  test("trims spaces around the line number", () => {
    const labels = labelsOf([
      AUDIO,
      { kind: "text", start: 121, text: " 4\r\n" },
    ]);
    expect(labels).toEqual([{ line: 4, start: parseMs(1000) }]);
  });

  test("orders the labels by line", () => {
    const labels = labelsOf([
      AUDIO,
      { kind: "text", start: 241, text: "2" },
      { kind: "text", start: 121, text: "1" },
    ]);
    expect(labels.map((label) => label.line)).toEqual([1, 2]);
  });

  test("rejects a text that is not a line number", () => {
    expect(() =>
      labelsOf([AUDIO, { kind: "text", start: 121, text: "風が吹く" }]),
    ).toThrow('object [1]: text must be a line number: "風が吹く"');
  });

  test("rejects a line labeled twice", () => {
    expect(() =>
      labelsOf([
        AUDIO,
        { kind: "text", start: 121, text: "1" },
        { kind: "text", start: 241, text: "1" },
      ]),
    ).toThrow("object [2]: line 1 is labeled twice");
  });

  test("rejects a text before the audio starts", () => {
    expect(() =>
      labelsOf([AUDIO, { kind: "text", start: 31, text: "1" }]),
    ).toThrow("object [1]: starts before the audio");
  });

  test("rejects a project without audio", () => {
    expect(() => labelsOf([{ kind: "text", start: 1, text: "1" }])).toThrow(
      "expected one audio object, found 0",
    );
  });

  test("rejects a project with two audio objects", () => {
    expect(() => labelsOf([AUDIO, AUDIO])).toThrow(
      "expected one audio object, found 2",
    );
  });

  test("rejects audio played at another speed", () => {
    expect(() =>
      labelsOf([{ kind: "audio", start: 1, speed: "50.0" }]),
    ).toThrow("object [0]: audio must play at 100% speed, not 50.0");
  });

  test("rejects a project without text", () => {
    expect(() => labelsOf([AUDIO])).toThrow("no text objects");
  });
});

describe("parseExo", () => {
  test("rejects a file without the exedit header", () => {
    expect(() => parseExo("[0]\r\nstart=1\r\n")).toThrow("[exedit]");
  });

  test("rejects a frame rate that is not a positive integer", () => {
    expect(() => parseExo(exo([AUDIO], 0))).toThrow("rate");
  });
});

describe("formatAudacityLabels", () => {
  test("writes point labels in start order", () => {
    const text = formatAudacityLabels([
      { line: 2, start: parseMs(61333) },
      { line: 1, start: parseMs(3500) },
    ]);
    expect(text).toBe("3.500000\t3.500000\t1\n61.333000\t61.333000\t2\n");
  });

  test("reads back through the label parser", () => {
    const labels = [
      { line: 1, start: parseMs(3500) },
      { line: 2, start: parseMs(61333) },
    ];
    const parsed = parseAudacityLabels(formatAudacityLabels(labels));
    expect(parsed).toEqual(labels);
  });
});
