import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { Welcome } from "@/components/workspace/welcome";
import { zhCN } from "@/core/i18n/locales/zh-CN";

rs.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ t: zhCN, locale: "zh-CN" }),
}));

describe("Welcome component", () => {
  beforeEach(() => {
    rs.useFakeTimers();
    // 2026-10-27 is a Tuesday (星期二)
    rs.setSystemTime(new Date(2026, 9, 27, 10, 0, 0));
  });

  afterEach(() => {
    cleanup();
    rs.useRealTimers();
  });

  test("renders system date with year, month, day, and weekday", () => {
    const { container } = render(<Welcome />);

    // In Chinese, 2026年10月27日 星期二 (AuroraText renders sr-only + aria-hidden)
    const elements = screen.getAllByText("2026年10月27日 星期二");
    expect(elements.length).toBeGreaterThan(0);
    // Verify old static greeting and wave emoji are gone
    expect(screen.queryByText("你好，欢迎回来！")).toBeNull();
    expect(screen.queryByText("👋")).toBeNull();
    // Verify calendar icon SVG is rendered
    expect(container.querySelector("svg")).not.toBeNull();
  });

  test("renders updated welcome description", () => {
    render(<Welcome />);

    expect(
      screen.getByText(
        "欢迎使用小易，小易可以帮你检索知识库文档，搜索网络、分析数据，更多功能，敬请期待~",
      ),
    ).toBeDefined();
  });
});
