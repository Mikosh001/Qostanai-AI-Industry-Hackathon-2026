import { test, expect } from "@playwright/test";
test("Teacher signs in and saves an organization profile", async ({ page }) => {
  await page.goto("/?role=teacher");
  await expect(
    page.getByRole("heading", { name: "Қош келдіңіз" }),
  ).toBeVisible();
  await page
    .getByLabel("Құпиясөз", { exact: true })
    .fill(process.env.SERGEK_TEST_PASSWORD || "AcceptanceTeacher123!");
  await page.getByRole("button", { name: "Панельге кіру" }).click();
  await expect(
    page.getByRole("heading", { name: "Бәрі бір панельде." }),
  ).toBeVisible();
  await page.screenshot({
    path: "tests/browser/screens/dashboard.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Емтихан ережелері", exact: true })
    .click();
  await page
    .getByLabel("Университет", { exact: true })
    .fill("Sergек — таныстыру ортасы");
  await page.getByRole("button", { name: "Сақтау", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.getByRole("button", { name: "Диагностика", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Диагностика", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "tests/browser/screens/diagnostics.png",
    fullPage: true,
  });
});
test("Technical noise stays outside review flags and never polls missing evidence", async ({
  page,
}) => {
  await page.goto("/?role=teacher");
  await page
    .getByLabel("Құпиясөз", { exact: true })
    .fill(process.env.SERGEK_TEST_PASSWORD || "AcceptanceTeacher123!");
  await page.getByRole("button", { name: "Панельге кіру" }).click();
  await page.getByText("Review fixture", { exact: true }).click();
  await expect(page.locator(".timeline-event")).toHaveCount(1);
  await expect(page.locator(".timeline-event")).toContainText("Телефон");
  await page.getByLabel("Техникалық журналды да көрсету").check();
  await expect(page.locator(".timeline-event")).toHaveCount(5);
  let evidenceRequests = 0;
  page.on("request", (request) => {
    if (request.url().includes("/evidence")) evidenceRequests++;
  });
  await page
    .locator(".timeline-event")
    .filter({ hasText: "Сыртқы сілтеме бұғатталды" })
    .click();
  await expect(
    page.getByRole("button", { name: "Негізсіз деп белгілеу" }),
  ).toHaveCount(0);
  await expect(page.getByText("Осы оқиғада бейне үзіндісі жоқ.")).toBeVisible();
  await page.waitForTimeout(1400);
  expect(evidenceRequests).toBe(0);
});
test("Student browser explicitly requires desktop and consent", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /Біліміңізге назар аударыңыз/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Moodle-ға кіру" }),
  ).toBeDisabled();
  await page.screenshot({
    path: "tests/browser/screens/student.png",
    fullPage: true,
  });
});
