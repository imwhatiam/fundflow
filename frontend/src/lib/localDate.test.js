import assert from "node:assert/strict";
import test from "node:test";

import { formatLocalDate } from "./localDate.js";

test("formatLocalDate uses local calendar components rather than UTC serialization", () => {
  const value = { getFullYear: () => 2026, getMonth: () => 8, getDate: () => 3 };

  assert.equal(formatLocalDate(value), "2026-09-03");
});

test("formatLocalDate zero-pads month and day", () => {
  const value = { getFullYear: () => 2026, getMonth: () => 0, getDate: () => 7 };

  assert.equal(formatLocalDate(value), "2026-01-07");
});
