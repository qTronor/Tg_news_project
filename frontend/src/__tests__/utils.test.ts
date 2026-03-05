import { formatNumber, sentimentColor, sentimentLabel, entityTypeColor } from "@/lib/utils";

describe("formatNumber", () => {
  it("returns raw number below 1K", () => {
    expect(formatNumber(0)).toBe("0");
    expect(formatNumber(999)).toBe("999");
  });

  it("formats thousands as K", () => {
    expect(formatNumber(1_000)).toBe("1.0K");
    expect(formatNumber(1_500)).toBe("1.5K");
    expect(formatNumber(999_999)).toBe("1000.0K");
  });

  it("formats millions as M", () => {
    expect(formatNumber(1_000_000)).toBe("1.0M");
    expect(formatNumber(2_500_000)).toBe("2.5M");
  });
});

describe("sentimentColor", () => {
  it("returns positive color for score > 0.2", () => {
    expect(sentimentColor(0.5)).toBe("var(--positive)");
  });

  it("returns negative color for score < -0.2", () => {
    expect(sentimentColor(-0.5)).toBe("var(--negative)");
  });

  it("returns neutral color for score between -0.2 and 0.2", () => {
    expect(sentimentColor(0)).toBe("var(--neutral-sentiment)");
    expect(sentimentColor(0.2)).toBe("var(--neutral-sentiment)");
    expect(sentimentColor(-0.2)).toBe("var(--neutral-sentiment)");
  });
});

describe("sentimentLabel", () => {
  it("returns correct labels", () => {
    expect(sentimentLabel(0.5)).toBe("Positive");
    expect(sentimentLabel(-0.5)).toBe("Negative");
    expect(sentimentLabel(0)).toBe("Neutral");
  });
});

describe("entityTypeColor", () => {
  it("maps known types", () => {
    expect(entityTypeColor("PER")).toBe("var(--entity-per)");
    expect(entityTypeColor("ORG")).toBe("var(--entity-org)");
    expect(entityTypeColor("LOC")).toBe("var(--entity-loc)");
    expect(entityTypeColor("per")).toBe("var(--entity-per)");
  });

  it("returns misc for unknown types", () => {
    expect(entityTypeColor("MISC")).toBe("var(--entity-misc)");
    expect(entityTypeColor("UNKNOWN")).toBe("var(--entity-misc)");
  });
});
