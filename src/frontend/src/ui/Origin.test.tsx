import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { OriginBadge } from "./Origin";

describe("OriginBadge", () => {
  it("показывает короткую подпись для известного origin", () => {
    render(<OriginBadge origin="measured" label="T6" />);
    expect(screen.getByRole("note")).toHaveTextContent("T6: измерение");
  });

  it("не путает отсутствующий origin с неизвестным происхождением по данным", () => {
    render(<OriginBadge origin={null} />);
    const node = screen.getByRole("note");
    expect(node).toHaveTextContent("не передавалось");
    expect(node.className).toContain("origin--absent");
  });

  it("не показывает произвольную строку как валидный origin", () => {
    render(<OriginBadge origin="unknown_key" />);
    expect(screen.getByRole("note")).toHaveTextContent("не передавалось");
  });
});
