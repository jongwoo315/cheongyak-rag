// OpenAI를 부르지 않는 화면 검사: 입력 유지와 좁은 폭.
import { expect, test } from "@playwright/test";

const FIRST = "2026000103";
const SECOND = "2026000517";
const ready = '[data-testid="profile-form"][data-ready="true"]';

test("입력 값이 같은 탭의 다른 공고 페이지에도 채워져 있고 localStorage에는 없다", async ({ page }) => {
  await page.goto(`/notices/${FIRST}`);
  await page.waitForSelector(ready);
  await page.locator('[name="birth_date"]').fill("1985-04-10");
  await page.locator('[name="married"]').selectOption("true");
  await page.locator('[name="children_unmarried"]').fill("2");
  await page.goto(`/notices/${SECOND}`);
  await page.waitForSelector(ready);
  await expect(page.locator('[name="birth_date"]')).toHaveValue("1985-04-10");
  await expect(page.locator('[name="married"]')).toHaveValue("true");
  await expect(page.locator('[name="children_unmarried"]')).toHaveValue("2");
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
});

test("폭 375px에서 가로 스크롤이 없다", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto(`/notices/${FIRST}`);
  await page.waitForSelector(ready);
  const w = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(w).toBeLessThanOrEqual(375);
});

test("입력 칸이 Profile 칸 15개다", async ({ page }) => {
  await page.goto(`/notices/${FIRST}`);
  await page.waitForSelector(ready);
  expect(await page.locator('form [name]').count()).toBe(15);
});
