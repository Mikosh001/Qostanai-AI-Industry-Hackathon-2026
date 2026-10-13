import { test, expect } from "@playwright/test";

async function mockedDesktop(page: any, ready = true) {
  await page.addInitScript(
    ({ ready }: { ready: boolean }) => {
      let scan = "idle";
      (window as any).sergek = {
        onLaunch: () => () => {},
        invoke: async (command: string) => {
          if (command === "get-language") return { language: null };
          if (command === "info") return { desktop: true };
          if (command === "set-language") return { ok: true };
          if (command === "security-scan") scan = "running";
          if (command.startsWith("security-"))
            return {
              packaged: true,
              integrity: { ready: true },
              antimalware: {
                ready,
                available: true,
                realtime_enabled: ready,
                tamper_protected: true,
                active_threats: 0,
                signature_age_days: 0,
                scan: { state: scan },
              },
            };
          throw new Error("Unsupported mock operation");
        },
      };
    },
    { ready },
  );
}
test("Security center follows all three languages and shows an actual pending scan state", async ({
  page,
}) => {
  await mockedDesktop(page);
  await page.goto("/");
  const card = page.locator(".security-center");
  await expect(card).toContainText("Тексерілді");
  await card.locator("summary").click();
  await expect(card).toContainText(
    "Файлдар тексерілді және ауыстырудан қорғалған.",
  );
  await page.locator(".language-selector select").selectOption("ru");
  await expect(card).toContainText("Защита компьютера");
  await page.locator(".language-selector select").selectOption("en");
  await expect(card).toContainText("Computer protection");
  await card.getByRole("button", { name: "Scan files", exact: true }).click();
  await expect(card).toContainText("Scanning application files…");
  await expect(
    card.getByRole("button", { name: "Scan files", exact: true }),
  ).toBeDisabled();
});
test("Disabled realtime antivirus is not presented as verified", async ({
  page,
}) => {
  await mockedDesktop(page, false);
  await page.goto("/");
  const card = page.locator(".security-center");
  await card.locator("summary").click();
  await expect(card.locator("summary")).toContainText("Тексеру қажет");
  await expect(card).toContainText("Windows антивирус қорғанысын қосу қажет.");
});
test("Expanded security center remains usable on a narrow screen", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await mockedDesktop(page);
  await page.goto("/");
  await page.locator(".security-center summary").click();
  await expect(
    page.getByRole("button", { name: "Файлдарды сканерлеу", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
