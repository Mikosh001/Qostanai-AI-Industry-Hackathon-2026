import { test, expect } from "@playwright/test";

async function login(page: any) {
  await page.goto("/?role=teacher");
  await page
    .getByLabel("Құпиясөз", { exact: true })
    .fill(process.env.SERGEK_TEST_PASSWORD || "AcceptanceTeacher123!");
  await page.getByRole("button", { name: "Панельге кіру" }).click();
}

test("Teacher can collapse raw preparation JSON and see an explained priority", async ({
  page,
}) => {
  await login(page);
  await expect(page.getByLabel("Сессияларды реттеу")).toHaveValue("priority");
  await page.getByText("Review fixture", { exact: true }).click();
  const technical = page.locator(".preflight-details");
  await expect(technical.locator("pre")).toBeHidden();
  await technical.locator("summary").click();
  await expect(technical.locator("pre")).toBeVisible();
  await technical.locator("summary").click();
  await expect(technical.locator("pre")).toBeHidden();
  await expect(page.locator(".review-summary [role=meter]")).toHaveAttribute(
    "aria-valuenow",
    "10",
  );
  await expect(page.locator(".review-reasons")).toContainText(
    "Телефон анықталды",
  );
  await page.getByLabel("Тек тексерілмеген бақылаулар").check();
  await expect(page.locator(".timeline-event")).toHaveCount(1);
  await expect(page.locator(".timeline-event")).toContainText("10 балл");
  await page.locator(".timeline-event").click();
  await expect(page.locator(".episode-history")).toContainText("0.0 секунд · 5 балл");
  await expect(page.locator(".episode-history")).toContainText("3.0 секунд · 10 балл");
  await page.getByRole("button",{name:"Жабу",exact:true}).click();
  await page.screenshot({
    path: "tests/browser/screens/feedback-teacher.png",
    fullPage: true,
  });
});

test("Student warnings persist with a duration scale in all three languages", async ({
  page,
}) => {
  await page.addInitScript(() => {
    let phase = "preflight";
    const session = () => ({
      id: "feedback-fixture",
      status: phase,
      created: new Date().toISOString(),
      data: {
        student: "UI feedback fixture",
        exam: "Moodle feedback fixture",
        platform: "moodle",
        policy: { camera_required: false, microphone_required: false },
        mode: "monitor",
      },
    });
    (window as any).sergek = {
      onLaunch: () => () => {},
      invoke: async (command: string) => {
        if (command === "get-language") return { language: "kk" };
        if (command === "info") return { launch: "fixture-token" };
        if (command === "resolve-launch")
          return {
            student: "UI feedback fixture",
            exam: "Moodle feedback fixture",
            platform: "moodle",
          };
        if (command === "create") return session();
        if (command === "start") {
          phase = "active";
          return session();
        }
        if (command === "snapshot")
          return {
            session: session(),
            signals: { faces: 1, quality: "good" },
            guard: { available: true },
            status: { identity_enrolled: true },
            feedback: {
              active: phase === "active",
              analysis_fresh: true,
              review: { score: 5, pending_episodes: 1 },
              alerts: [
                {
                  kind: "phone_brief",
                  points: 5,
                  next_points: 10,
                  active: true,
                  seconds: 0.7,
                  threshold: 2,
                  progress: 0.35,
                  saved: true,
                },
                {
                  kind: "gaze_side",
                  active: true,
                  seconds: 3,
                  threshold: 5,
                  progress: 0.6,
                  saved: false,
                },
                {
                  kind: "sustained_noise",
                  active: true,
                  seconds: 0.2,
                  threshold: 0.5,
                  progress: 0.4,
                  saved: false,
                  points: 0,
                },
              ],
            },
          };
        return {};
      },
    };
  });
  await page.goto("/");
  await page.locator(".checkbox input").check();
  await page.getByRole("button", { name: "Фотоға өту" }).click();
  await page.getByRole("button", { name: "Тест бетіне өту" }).click();
  const dock = page.locator(".student-feedback.docked");
  await expect(dock).toBeVisible();
  await expect(dock).toContainText("Телефонды алып тастаңыз.");
  await expect(dock).toContainText("5 балл");
  await expect(dock).toContainText("Экранға қараңыз.");
  await expect(dock.locator("[role=progressbar]").first()).toHaveAttribute(
    "aria-valuenow",
    "35",
  );
  await expect(dock.locator("[role=meter]")).toHaveAttribute(
    "aria-valuenow",
    "5",
  );
  await page.locator(".language-selector select").selectOption("ru");
  await expect(dock).toContainText("Уберите телефон.");
  await expect(dock).toContainText("Смотрите на экран.");
  await page.screenshot({
    path: "tests/browser/screens/feedback-student-ru.png",
    fullPage: true,
  });
  await page.locator(".language-selector select").selectOption("en");
  await expect(dock).toContainText("Put the phone away.");
  await expect(dock).toContainText("Look at the screen.");
  await page.setViewportSize({ width: 800, height: 700 });
  await expect(
    dock.getByText("Reduce background noise.", { exact: true }),
  ).toBeVisible();
  const bounds = await dock.boundingBox();
  expect(bounds?.height).toBe(112);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
