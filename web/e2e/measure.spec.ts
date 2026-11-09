// #84 징후 1·2 측정. 화면 코드(web/app)를 import하지 않는다.
// 먼저 `python -m cheongyak_rag.web_report before`로 runs/84/expected.json을 만든다.
// 화면에서 읽은 값만 runs/84/raw.json에 쓰고, 기대값과 맞추는 계산은 파이썬(`after`)이 한다.
// #85: 아래 환경 변수로 배포 사이트를 잰다. 안 주면 #84와 똑같이 동작한다.
//   WEB_BASE_URL     잴 사이트 (기본 http://127.0.0.1:3184)
//   MEASURE_RUN_DIR  expected.json을 읽고 raw.json을 쓰는 디렉터리 (기본 runs/84, repo 기준)
//   MEASURE_WAIT_MS  쌍마다 결과를 기다리는 시간 (기본 120000)
//   MEASURE_SHOT_DIR 스크린샷 디렉터리 (기본 docs/84-web, repo 기준)
import { expect, test, type Browser } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const REPO = path.resolve(__dirname, "../..");
const RUN_DIR = path.resolve(REPO, process.env.MEASURE_RUN_DIR ?? "runs/84");
const SHOT_DIR = path.resolve(REPO, process.env.MEASURE_SHOT_DIR ?? "docs/84-web");
const WEB = process.env.WEB_BASE_URL ?? "http://127.0.0.1:3184";
const WAIT_MS = Number(process.env.MEASURE_WAIT_MS ?? 120_000);

type Expected = {
  notices: { house_manage_no: string; house_nm: string; n_models: number }[];
  pairs: { notice: string; profile: string; profile_json: Record<string, unknown> }[];
};
const exp: Expected = JSON.parse(fs.readFileSync(path.join(RUN_DIR, "expected.json"), "utf8"));

const decode = (s: string) =>
  s
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");

// JS 없이 HTTP로만 받는다 (fetch는 스크립트를 실행하지 않는다).
async function fetchPage(hmn: string) {
  const res = await fetch(`${WEB}/notices/${encodeURIComponent(hmn)}`);
  const html = await res.text();
  const title = /<title>([^<]*)<\/title>/.exec(html)?.[1];
  const table = html.split('data-testid="models-table"')[1] ?? "";
  const tbody = /<tbody>([\s\S]*?)<\/tbody>/.exec(table)?.[1] ?? "";
  return {
    house_manage_no: hmn,
    status: res.status,
    title: title === undefined ? null : decode(title),
    rows: (tbody.match(/<tr[ >]/g) ?? []).length,
  };
}

async function countLinks() {
  const html = await (await fetch(`${WEB}/`)).text();
  return new Set(html.match(/href="\/notices\/[^"]+"/g) ?? []).size;
}

type Screen = {
  verdict: string;
  routes: [string, string][];
  n_checklist: number;
};

async function ask(browser: Browser, notice: string, profile: Record<string, unknown>, shot?: string) {
  const ctx = await browser.newContext({ viewport: { width: 1000, height: 900 } }); // sessionStorage가 빈 채로 시작한다
  const page = await ctx.newPage();
  try {
    await page.goto(`${WEB}/notices/${notice}`);
    await page.waitForSelector('[data-testid="profile-form"][data-ready="true"]');
    for (const [name, value] of Object.entries(profile)) {
      if (value === null || value === undefined) continue; // 빈 칸 · 「모름」
      const el = page.locator(`[name="${name}"]`);
      if (typeof value === "boolean") await el.selectOption(String(value));
      else await el.fill(String(value));
    }
    const t0 = Date.now();
    await page.getByRole("button", { name: "판정하기" }).click();
    const outcome = page.locator('[data-testid="verdict-global"], [data-testid="error"]').first();
    try {
      await outcome.waitFor({ timeout: WAIT_MS });
    } catch {
      return { shown: false, seconds: (Date.now() - t0) / 1000, screen: null };
    }
    const seconds = (Date.now() - t0) / 1000;
    if ((await page.locator('[data-testid="error"]').count()) > 0) {
      return {
        shown: false,
        seconds,
        screen: null,
        error: await page.locator('[data-testid="error"]').innerText(),
      };
    }
    const screen: Screen = {
      verdict: (await page.locator('[data-testid="verdict-global"]').innerText()).trim(),
      routes: await page.locator('[data-testid="route-row"]').evaluateAll((rows) =>
        rows.map(
          (r) =>
            [
              r.getAttribute("data-route-key") ?? "",
              (r.querySelector('[data-testid="route-verdict"]') as HTMLElement).innerText.trim(),
            ] as [string, string],
        ),
      ),
      n_checklist: await page.locator('[data-testid="checklist-item"]').count(),
    };
    if (shot) {
      fs.mkdirSync(SHOT_DIR, { recursive: true });
      await page.screenshot({ path: path.join(SHOT_DIR, shot), fullPage: true });
    }
    return { shown: true, seconds, screen };
  } finally {
    await ctx.close();
  }
}

test("징후 1·2 — 공고 페이지 84개와 18쌍 질의", async ({ browser }) => {
  const pages = [];
  for (const n of exp.notices) pages.push(await fetchPage(n.house_manage_no));
  const links = await countLinks();

  const SHOTS: Record<string, string> = {
    "2026000103×full": "verdict-full.png",
    "2026000103×empty": "verdict-empty.png",
  };
  const pairs = [];
  for (const p of exp.pairs) {
    const shot = SHOTS[`${p.notice}×${p.profile}`];
    const attempts = [await ask(browser, p.notice, p.profile_json, shot)];
    if (!attempts[0].shown) attempts.push(await ask(browser, p.notice, p.profile_json, shot)); // 그 쌍만 한 번 더
    pairs.push({ notice: p.notice, profile: p.profile, attempts });
  }
  fs.mkdirSync(RUN_DIR, { recursive: true });
  fs.writeFileSync(path.join(RUN_DIR, "raw.json"), JSON.stringify({ pages, links, pairs }, null, 2));
  expect(pairs.length).toBe(exp.pairs.length); // 값의 통과 여부는 파이썬 `after`가 판정한다
});
