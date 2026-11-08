import { describe, expect, test } from "bun:test";
import {
  type FrameRate,
  type Ms,
  msToFrame,
  parseFrameRate,
  parseMs,
} from "../../src/domain/time";

const FPS_30: FrameRate = parseFrameRate({ rate: 30, scale: 1 });
const FPS_29_97: FrameRate = parseFrameRate({ rate: 30000, scale: 1001 });
const FPS_59_94: FrameRate = parseFrameRate({ rate: 60000, scale: 1001 });

const HOURS_24_MS = 24 * 60 * 60 * 1000;

describe("parseMs", () => {
  test("accepts zero", () => {
    const input = 0;
    const result: number = parseMs(input);
    expect(result).toBe(0);
  });

  test("accepts a positive integer", () => {
    const input = 4100;
    const result: number = parseMs(input);
    expect(result).toBe(4100);
  });

  test("rejects a negative number", () => {
    const input = -1;
    expect(() => parseMs(input)).toThrow();
  });

  test("rejects a non-integer number", () => {
    const input = 4100.5;
    expect(() => parseMs(input)).toThrow();
  });

  test("rejects NaN", () => {
    const input = Number.NaN;
    expect(() => parseMs(input)).toThrow();
  });

  test("rejects Infinity", () => {
    const input = Number.POSITIVE_INFINITY;
    expect(() => parseMs(input)).toThrow();
  });

  test("rejects a numeric string", () => {
    const input = "4100";
    expect(() => parseMs(input)).toThrow();
  });
});

describe("parseFrameRate", () => {
  test("accepts 30000/1001", () => {
    const input = { rate: 30000, scale: 1001 };
    const result: { rate: number; scale: number } = parseFrameRate(input);
    expect(result).toEqual({ rate: 30000, scale: 1001 });
  });

  test("rejects a zero scale", () => {
    const input = { rate: 30, scale: 0 };
    expect(() => parseFrameRate(input)).toThrow();
  });

  test("rejects a non-integer rate", () => {
    const input = { rate: 29.97, scale: 1 };
    expect(() => parseFrameRate(input)).toThrow();
  });
});

describe("msToFrame", () => {
  test("4100 ms at 30/1 with origin 0 is frame 123 (float seconds would give 122)", () => {
    const ms = parseMs(4100);
    const result = msToFrame(ms, FPS_30, 0);
    expect(result).toBe(123);
  });

  test("0 ms with origin 1 is frame 1", () => {
    const ms = parseMs(0);
    const result = msToFrame(ms, FPS_30, 1);
    expect(result).toBe(1);
  });

  test("0 ms with origin 0 is frame 0", () => {
    const ms = parseMs(0);
    const result = msToFrame(ms, FPS_30, 0);
    expect(result).toBe(0);
  });

  test("floors rather than rounds (33 ms at 30/1 is still frame 0)", () => {
    const ms = parseMs(33);
    const result = msToFrame(ms, FPS_30, 0);
    expect(result).toBe(0);
  });

  test("the first whole ms past a frame boundary advances (34 ms at 30/1 is frame 1)", () => {
    const ms = parseMs(34);
    const result = msToFrame(ms, FPS_30, 0);
    expect(result).toBe(1);
  });

  test("an exact frame boundary starts the next frame (100 ms at 30/1 is frame 3)", () => {
    const ms = parseMs(100);
    const result = msToFrame(ms, FPS_30, 0);
    expect(result).toBe(3);
  });

  test("an unparsed frame rate literal is rejected by the type checker", () => {
    const ms = parseMs(0);
    const unparsed = { rate: 30, scale: 0 };
    // @ts-expect-error FrameRate is branded; only parseFrameRate output is accepted.
    const call = () => msToFrame(ms, unparsed, 0);
    expect(call).toThrow(RangeError);
  });

  test("1000 ms at 30000/1001 with origin 0 is frame 29", () => {
    const ms = parseMs(1000);
    const result = msToFrame(ms, FPS_29_97, 0);
    expect(result).toBe(29);
  });

  test("1001 ms at 30000/1001 with origin 0 is frame 30", () => {
    // 1001 * 30000 / (1001 * 1000) = 30 exactly.
    const ms = parseMs(1001);
    const result = msToFrame(ms, FPS_29_97, 0);
    expect(result).toBe(30);
  });

  test("1000 ms at 30000/1001 with origin 1 is frame 30", () => {
    const ms = parseMs(1000);
    const result = msToFrame(ms, FPS_29_97, 1);
    expect(result).toBe(30);
  });

  test("60 s at 30000/1001 with origin 0 is frame 1798", () => {
    // 60000 * 30000 / 1_001_000 = 1798.2...
    const ms = parseMs(60_000);
    const result = msToFrame(ms, FPS_29_97, 0);
    expect(result).toBe(1798);
  });

  test("24 h at 30/1 with origin 0 is frame 2_592_000", () => {
    const ms = parseMs(HOURS_24_MS);
    const result = msToFrame(ms, FPS_30, 0);
    expect(result).toBe(2_592_000);
  });

  test("24 h at 60000/1001 with origin 0 is frame 5_178_821", () => {
    // 86_400_000 * 60000 / 1_001_000 = 5_178_821.178... -> 5_178_821
    const ms = parseMs(HOURS_24_MS);
    const result = msToFrame(ms, FPS_59_94, 0);
    expect(result).toBe(5_178_821);
  });

  test("stays exact where a Number product would pass 2^53", () => {
    // ms * rate = (2^53 - 1) * 60000 is far beyond 2^53; the answer is
    // floor((2^53 - 1) * 60000 / 1_001_000) computed with BigInt.
    const ms = parseMs(Number.MAX_SAFE_INTEGER);
    const expected = Number(
      (BigInt(Number.MAX_SAFE_INTEGER) * 60000n) / 1_001_000n,
    );
    const result = msToFrame(ms, FPS_59_94, 0);
    expect(result).toBe(expected);
  });

  test("throws RangeError when the frame index is not a safe integer", () => {
    const ms = parseMs(Number.MAX_SAFE_INTEGER);
    const hugeRate = parseFrameRate({
      rate: Number.MAX_SAFE_INTEGER,
      scale: 1,
    });
    expect(() => msToFrame(ms, hugeRate, 0)).toThrow(RangeError);
  });
});

describe("Ms type", () => {
  test("a parsed Ms is usable as a number", () => {
    const ms: Ms = parseMs(250);
    expect(ms + 1).toBe(251);
  });
});
