import { describe, expect, it } from "vitest";
import { fullName, labelize, money, pct, recordedAmount } from "./format";

describe("format", () => {
  it("formats money as INR without inventing values", () => {
    expect(money(0)).toContain("0");
    expect(money(null)).toContain("0");
    expect(money(120000)).toMatch(/₹|INR/);
  });

  it("keeps a recorded currency and leaves a missing currency unknown", () => {
    expect(recordedAmount("250001.00", "USD")).toBe("USD 250,001.00");
    expect(recordedAmount("10.00", "")).toBe("10.00 · currency unknown");
    expect(recordedAmount(null, "INR")).toBe("Not recorded");
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
