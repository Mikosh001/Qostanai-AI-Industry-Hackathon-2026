import { test, expect } from "@playwright/test";

test("Language persists across reload and student/teacher navigation without clearing input", async ({
  page,
}) => {
  await page.goto("/");
  const selector = page.locator(".language-selector select");
  await expect(selector).toHaveValue("kk");
  await selector.selectOption("ru");
  await expect(
    page.getByRole("heading", { name: /Сосредоточьтесь на знаниях/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Панель преподавателя" }).click();
  const password = page.getByLabel("Пароль", { exact: true });
  await password.fill("not-the-password");
  await page.getByRole("button", { name: "Войти в панель" }).click();
  await expect(page.getByRole("alert")).toContainText("Неверный пароль");
  await selector.selectOption("en");
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue(
    "not-the-password",
  );
  await expect(page.getByRole("alert")).toContainText("Incorrect password");
  await page.reload();
  await expect(selector).toHaveValue("en");
  await expect(
    page.getByRole("heading", { name: /Focus on your knowledge/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Teacher dashboard" }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome", exact: true }),
  ).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await page.getByRole("button", { name: "Student mode" }).click();
  await expect(
    page.getByRole("heading", { name: /Focus on your knowledge/ }),
  ).toBeVisible();
  await selector.selectOption("kk");
  await expect(
    page.getByRole("heading", { name: /Біліміңізге назар аударыңыз/ }),
  ).toBeVisible();
});

test("Teacher events, verdicts, forms and PDF links follow the selected language", async ({
  page,
}) => {
  await page.goto("/?role=teacher");
  const selector = page.locator(".language-selector select");
  await selector.selectOption("en");
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.SERGEK_TEST_PASSWORD || "AcceptanceTeacher123!");
  await page.getByRole("button", { name: "Sign in to dashboard" }).click();
  await page.getByText("Review fixture", { exact: true }).click();
  await expect(page.locator(".timeline-event")).toHaveCount(1);
  await expect(page.locator(".timeline-event")).toContainText("Phone detected");
  await expect(page.locator(".timeline-event")).toContainText("Pending review");
  await expect(
    page.getByRole("link", { name: "PDF", exact: true }),
  ).toHaveAttribute("href", /lang=en$/);
  await page.locator(".timeline-event").click();
  await page
    .getByLabel("Teacher comment")
    .fill("Қазақша пікір / Russian comment / English note");
  await selector.selectOption("ru");
  await expect(page.getByLabel("Комментарий преподавателя")).toHaveValue(
    "Қазақша пікір / Russian comment / English note",
  );
  await expect(
    page.getByRole("heading", { name: "Обнаружен телефон" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "PDF", exact: true }),
  ).toHaveAttribute("href", /lang=ru$/);
  await page
    .getByRole("button", { name: "Правила экзамена", exact: true })
    .click();
  await page
    .getByLabel("Университет", { exact: true })
    .fill("Тіл ауыстырғанда сақталатын университет");
  await selector.selectOption("en");
  await expect(page.getByLabel("University", { exact: true })).toHaveValue(
    "Тіл ауыстырғанда сақталатын университет",
  );
  await page.getByRole("button", { name: "Integration", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Platforms and classroom" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Diagnostics", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Diagnostics", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "tests/browser/screens/three-languages-en.png",
    fullPage: true,
  });
  await selector.selectOption("ru");
  await page.screenshot({
    path: "tests/browser/screens/three-languages-ru.png",
    fullPage: true,
  });
});

test("Unsupported saved language falls back to Kazakh", async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem("sergek.language", "unsupported"),
  );
  await page.goto("/");
  await expect(page.locator(".language-selector select")).toHaveValue("kk");
  await expect(page.locator("html")).toHaveAttribute("lang", "kk");
});
