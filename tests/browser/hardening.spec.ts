import { test, expect } from "@playwright/test";

async function login(page: any) {
  await page.goto("/?role=teacher");
  await page
    .getByLabel("Құпиясөз", { exact: true })
    .fill(process.env.SERGEK_TEST_PASSWORD || "AcceptanceTeacher123!");
  await page.getByRole("button", { name: "Панельге кіру" }).click();
  await expect(
    page.getByRole("heading", { name: "Бәрі бір панельде." }),
  ).toBeVisible();
}

test("Narrow student and teacher login pages retain controls without page overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Мұғалім панелі" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Мұғалім панелі" }).click();
  await expect(page.getByLabel("Құпиясөз", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("Narrow dashboard confines overflow to a keyboard-focusable sessions region", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  const region = page.getByRole("region", { name: "Сессиялар", exact: true });
  await expect(region).toBeVisible();
  await region.focus();
  await expect(region).toBeFocused();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("Dashboard warns when background refresh fails and clears the warning on recovery", async ({
  page,
}) => {
  await login(page);
  await page.route("**/api/session-page?*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Injected offline fixture" }),
    }),
  );
  await expect(page.getByRole("alert")).toContainText(
    "Панельдегі деректер ескірген болуы мүмкін",
    { timeout: 6000 },
  );
  await page.unroute("**/api/session-page?*");
  await expect(page.getByRole("alert")).toHaveCount(0, { timeout: 6000 });
});

test("Teacher sees incomplete evidence explicitly in a session report", async ({
  page,
}) => {
  await login(page);
  const sessions = await (await page.request.get("/api/sessions")).json();
  const sid = sessions[0].id;
  const detail = await (await page.request.get(`/api/sessions/${sid}`)).json();
  detail.session.data.evidence_incomplete = true;
  await page.route(`**/api/sessions/${sid}`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(detail),
    }),
  );
  await page.getByText("Review fixture", { exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Дәлелдердің бір бөлігі сақталмады",
  );
});

test("Teacher pages through a large class and searches across all pages",async({page})=>{
  await page.route('**/api/session-page?*',async route=>{
    const url=new URL(route.request().url());const offset=Number(url.searchParams.get('offset'));
    const search=url.searchParams.get('q');const count=search?1:205;
    const items=Array.from({length:search?1:Math.min(100,count-offset)},(_,i)=>({id:String(offset+i),status:'preflight',started:null,event_count:0,data:{student:search?'Student 204':'Student '+(offset+i),exam:'Pagination fixture',platform:'moodle'}}));
    await route.fulfill({json:{items,total:count,counts:{preflight:205},offset,limit:100}});
  });
  await login(page);
  await expect(page.getByText('Student 0',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Келесі бет',exact:true}).click();
  await expect(page.getByText('Student 100',{exact:true})).toBeVisible();
  await page.getByPlaceholder('Студент немесе емтихан').fill('Student 204');
  await expect(page.getByText('Student 204',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Келесі бет',exact:true})).toHaveCount(0);
});

test("Hub operator enrolls and revokes a real device without exposing its key in the list",async({page})=>{
  await login(page);
  await page.getByRole('button',{name:'Интеграция',exact:true}).click();
  await page.getByRole('button',{name:'Компьютерді тіркеу',exact:true}).click();
  await expect(page.locator('.secret-card')).toContainText('device_key');
  const secret=JSON.parse(await page.locator('.secret-card code').innerText());
  const listed=await(await page.request.get('/api/integration/devices')).json();
  expect(listed.find((d:any)=>d.id===secret.device_id)).toBeTruthy();
  expect(JSON.stringify(listed)).not.toContain(secret.device_key);
  await page.getByRole('button',{name:'Құрылғы рұқсатын тоқтату',exact:true}).last().click();
  await expect(page.getByRole('button',{name:'Құрылғы бұғатталған',exact:true}).last()).toBeDisabled();
});
