import { expect, test } from "@playwright/test";

test("renders a readable console foundation without horizontal overflow", async ({
  page,
}) => {
  await page.goto("/");

  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "AgentOps Incident Commander",
    }),
  ).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Console foundation ready");
  await expect(page.getByRole("listitem")).toHaveCount(3);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
});
