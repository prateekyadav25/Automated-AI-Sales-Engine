import { describe, expect, it } from "vitest";
import { fullName, labelize, money, pct } from "./format";

describe("format", () => {
  it("formats money as INR without inventing values", () => {
    expect(money(0)).toContain("0");
    expect(money(null)).toContain("0");
    expect(money(120000)).toMatch(/₹|INR/);
  });

  it("formats percent", () => {
    expect(pct(0.25)).toBe("25%");
  });

  it("joins names", () => {
    expect(fullName("Ada", "Khan")).toBe("Ada Khan");
  });

  it("labelizes stage keys", () => {
    expect(labelize("closed_won")).toBe("closed won");
  });
});
