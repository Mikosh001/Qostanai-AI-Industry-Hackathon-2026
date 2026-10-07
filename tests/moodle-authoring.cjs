const { chromium, expect } = require("@playwright/test");
const fs = require("fs"),
  path = require("path");
(async () => {
  const root = path.resolve(__dirname, ".."),
    lab = path.resolve(root, "../../work/local-moodle"),
    c = JSON.parse(fs.readFileSync(path.join(lab, "credentials.json"))),
    exam = JSON.parse(fs.readFileSync(path.join(lab, "exam.json")));
  const b = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const p = await b.newPage({ ignoreHTTPSErrors: true });
    const apiErrors = [];
    p.on("response", (response) => {
      if (
        response.status() >= 400 &&
        new URL(response.url()).pathname.includes("/preferences/")
      )
        apiErrors.push(response.status());
    });
    p.setDefaultTimeout(15000);
    await p.goto("https://localhost/login/index.php");
    await p.locator("#username").fill(c.moodle_teacher);
    await p.locator("#password").fill(c.moodle_teacher_password);
    await p.locator("#loginbtn").click();
    const marker = path.join(lab, "authoring-quiz.json");
    let authored;
    if (fs.existsSync(marker)) {
      authored = JSON.parse(fs.readFileSync(marker));
    } else {
      await p.goto(
        "https://localhost/course/modedit.php?add=quiz&course=" +
          exam.courseid +
          "&section=0",
      );
      await p.locator("#id_name").fill("Бағдарламалау негіздері — 5 сұрақ");
      await p.locator("#id_security a.fheader").click();
      await p.locator("#id_sergekrequired").check();
      await p.locator("#id_submitbutton").click();
      await p.waitForURL("**/mod/quiz/view.php?*");
      authored = {
        url: p.url(),
        cmid: new URL(p.url()).searchParams.get("id"),
        imported: false,
      };
      fs.writeFileSync(marker, JSON.stringify(authored));
    }
    await p.goto(
      "https://localhost/course/modedit.php?update=" +
        authored.cmid +
        "&return=1",
    );
    await p.locator("#id_security a.fheader").click();
    await expect(p.locator("#id_sergekrequired")).toBeChecked();
    await p.screenshot({
      path: path.join(root, "tests/browser/screens/moodle-quiz-settings.png"),
      fullPage: true,
    });
    if (!authored.imported) {
      await p.goto(
        "https://localhost/question/bank/importquestions/import.php?courseid=" +
          exam.courseid,
      );
      await p.locator("#id_format_gift").check();
      await p.locator("[name=newfilechoose]").click();
      await p.getByText("Upload a file", { exact: true }).click();
      await p
        .locator("input[type=file]")
        .setInputFiles(path.join(root, "docs/demo-questions.gift.txt"));
      await p
        .getByRole("button", { name: "Upload this file", exact: true })
        .click();
      await p.locator("#id_submitbutton").click();
      await expect(
        p.getByText("Importing 5 questions from file", { exact: false }),
      ).toBeVisible();
      authored.imported = true;
      fs.writeFileSync(marker, JSON.stringify(authored));
    }
    await p.goto("https://localhost/mod/quiz/edit.php?cmid=" + authored.cmid);
    if (!authored.added) {
      await p.getByRole("button", { name: "Add", exact: true }).first().click();
      await p.getByText("from question bank", { exact: true }).click();
      await expect
        .poll(
          () => p.getByRole("dialog").last().locator("select,input").count(),
          { timeout: 15000 },
        )
        .toBeGreaterThan(0);
      const dialog = p.getByRole("dialog").last();
      const category = dialog.locator("select#filter-value-category");
      const value = await category
        .locator("option")
        .filter({ hasText: "Sergек бағдарламалау" })
        .getAttribute("value");
      await dialog
        .getByRole("combobox", { name: "Category", exact: true })
        .fill("Sergек бағдарламалау");
      await dialog
        .getByRole("option")
        .filter({ hasText: "Sergек бағдарламалау" })
        .click();
      await expect
        .poll(() => category.inputValue(), { timeout: 5000 })
        .toBe(value);
      await p.waitForTimeout(250);
      await dialog
        .getByRole("button", { name: "Apply filters", exact: true })
        .click();
      await expect
        .poll(() => dialog.locator("input[type=checkbox]").count(), {
          timeout: 15000,
        })
        .toBeGreaterThan(4);
      for (const checkbox of await dialog
        .locator('input[type=checkbox][name^="q"]')
        .all())
        await checkbox.check();
      await dialog
        .getByRole("button", {
          name: "Add selected questions to the quiz",
          exact: true,
        })
        .click();
      await expect(p.getByText("Questions: 5", { exact: false })).toBeVisible();
      authored.added = true;
      fs.writeFileSync(marker, JSON.stringify(authored));
    }
    await expect(p.getByText("Questions: 5", { exact: false })).toBeVisible();
    // Reopen the bank to verify the preference transport after the first filter has stored false.
    await p.getByRole("button", { name: "Add", exact: true }).first().click();
    await p.getByText("from question bank", { exact: true }).first().click();
    await expect(
      p
        .getByRole("dialog")
        .last()
        .getByRole("combobox", { name: "Category", exact: true }),
    ).toBeVisible();
    await p.waitForTimeout(500);
    if (apiErrors.length) throw new Error("Moodle preference route failed");
    await p.screenshot({
      path: path.join(root, "tests/browser/screens/moodle-authored-quiz.png"),
      fullPage: true,
    });
    console.log(
      JSON.stringify({
        passed: true,
        editingTeacherLogin: true,
        createdProtectedQuiz: true,
        sergekRuleSaved: true,
        giftQuestionsImported: 5,
        questionsAddedToQuiz: 5,
        preferenceRequestsAccepted: true,
        quiz: authored.url,
      }),
    );
  } finally {
    await b.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
