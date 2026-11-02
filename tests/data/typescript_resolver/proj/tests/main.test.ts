import { describe, expect, it } from "vitest";
import { run } from "../src/main";

function helper() {}

describe("run", () => {
  it("works", () => {
    helper();
    run();
    expect(1).toBe(1);
  });
});
