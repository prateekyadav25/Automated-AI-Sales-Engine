import { describe, expect, it } from "vitest";
import { coverageText, metricText, provenanceLabel, rangeQuery, statusTone, utcDays } from "./growth";

describe("growth formatting", () => {
  it("shows missing provider values as unavailable, never zero", () => {
    expect(metricText(null)).toBe("Unavailable");
    expect(metricText(undefined)).toBe("Unavailable");
    expect(metricText(0)).toBe("0");
    expect(metricText(1234.5, 1)).toBe("1,234.5");
  });

  it("states partial coverage plainly", () => {
    expect(coverageText({ value: 10, coverage_days: 3, range_days: 7 })).toBe("Partial: 3 of 7 days");
    expect(coverageText({ value: 10, coverage_days: 7, range_days: 7 })).toBe("7 of 7 days");
    expect(coverageText({ value: null, coverage_days: 0, range_days: 7 })).toBe("No reading");
  });

  it("labels fixture evidence as not live", () => {
    expect(provenanceLabel("fixture")).toBe("Fixture (not live)");
    expect(provenanceLabel("live")).toBe("Live provider");
    expect(provenanceLabel("custom_thing")).toBe("custom thing");
  });

  it("maps statuses to tones and builds range queries", () => {
    expect(statusTone("published")).toBe("ok");
    expect(statusTone("needs_reconnect")).toBe("rose");
    expect(statusTone("needs_review")).toBe("gold");
    expect(rangeQuery("7d", "", "", "")).toBe("range=7d");
    expect(rangeQuery("custom", "2026-10-01", "2026-10-07", "abc")).toBe("range=custom&start=2026-10-01&end=2026-10-07&account_id=abc");
  });

  it("states a report period as the UTC days it covers, end exclusive", () => {
    expect(utcDays("2026-10-28T00:00:00+00:00", "2026-10-29T00:00:00+00:00")).toBe("28 Oct 2026 (UTC day)");
    expect(utcDays("2026-10-22T00:00:00+00:00", "2026-10-29T00:00:00+00:00")).toBe("22 Oct 2026 to 28 Oct 2026 (UTC days)");
  });
});
