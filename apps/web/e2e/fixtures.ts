import { expect, type Page, test as base } from "@playwright/test";

/** Log in with the seeded demo account and wait for the app shell. */
export async function loginDemo(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByRole("button", { name: /demo account/i }).click();
  await page.waitForURL((u) => new URL(u).pathname === "/", { timeout: 60_000 });
  await expect(page.getByLabel("Message the copilot")).toBeVisible({ timeout: 30_000 });
}

/** Ask the copilot something and wait until streaming has finished. */
export async function ask(page: Page, text: string): Promise<void> {
  const answers = page.getByRole("button", { name: "Copy answer" }); // rendered only once an answer has finished streaming
  const before = await answers.count();
  const box = page.getByLabel("Message the copilot");
  await box.fill(text);
  await box.press("Enter");
  await expect(answers).toHaveCount(before + 1, { timeout: 90_000 });
}

export const test = base.extend<{ authed: Page }>({
  authed: async ({ page }, use) => {
    await loginDemo(page);
    await use(page);
  },
});

export { expect };
