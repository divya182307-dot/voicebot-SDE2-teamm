import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

async function advanceToApproval(page: import("@playwright/test").Page) {
  await page.getByRole("button", { name: "Start Session" }).click();
  for (let step = 0; step < 3; step += 1) {
    await page.getByRole("button", { name: "Advance Workflow" }).click();
  }
}

test.describe("Week 4 demo journeys", () => {
  test("normal approval flow runs entirely on demo data", async ({ page }) => {
    let backendRequests = 0;
    await page.route("**/sessions**", async (route) => {
      backendRequests += 1;
      await route.abort();
    });

    await page.goto("/?demo=1");
    await expect(
      page.getByText("The complete workflow runs on sample data without a backend or API keys."),
    ).toBeVisible();
    await expect(page.getByText("Transcript Timeline (4 messages)")).toBeVisible();

    await advanceToApproval(page);
    await page.getByRole("button", { name: "Open Approval Dialog" }).click();
    const dialog = page.getByRole("dialog", { name: "Approve or Reject Action" });
    await expect(dialog).toContainText("Save a study plan generated from this session's transcript");
    await expect(dialog).toContainText("Saving creates persistent study-plan content");
    await page.getByRole("button", { name: "Approve" }).click();

    await expect(page.getByText("Approval Decision: Approved")).toBeVisible();
    await expect(page.getByText("Actions executed: 1")).toBeVisible();
    await page.getByRole("button", { name: "Stop Session" }).click();
    await expect(page.getByText("Session Status: stopped")).toBeVisible();
    await page.screenshot({
      path: "test-results/week4-demo.png",
      fullPage: true,
    });
    expect(backendRequests).toBe(0);
  });

  test("rejecting approval marks the workflow rejected and executes nothing", async ({ page }) => {
    await page.goto("/?demo=1");
    await advanceToApproval(page);
    await page.getByRole("button", { name: "Open Approval Dialog" }).click();
    await page.getByRole("button", { name: "Reject" }).click();

    await expect(page.getByText(/Approval Decision: Rejected/)).toBeVisible();
    await expect(page.getByText("Actions executed: 0")).toBeVisible();
    await expect(page.getByRole("listitem").last()).toContainText("rejected");
  });

  test("approval dialog traps keyboard focus and Escape returns focus", async ({ page }) => {
    await page.goto("/?demo=1");
    await advanceToApproval(page);
    const openButton = page.getByRole("button", { name: "Open Approval Dialog" });
    await openButton.click();

    const approveButton = page.getByRole("button", { name: "Approve" });
    const rejectButton = page.getByRole("button", { name: "Reject" });
    await expect(approveButton).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(rejectButton).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(approveButton).toBeFocused();
    await page.keyboard.press("Escape");

    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(openButton).toBeFocused();
  });

  test("the demo has no automated accessibility violations", async ({ page }) => {
    await page.goto("/?demo=1");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });

  test("the approval dialog has no automated accessibility violations", async ({ page }) => {
    await page.goto("/?demo=1");
    await advanceToApproval(page);
    await page.getByRole("button", { name: "Open Approval Dialog" }).click();

    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });

  test("layout and approval dialog fit narrow mobile screens", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/?demo=1");
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(1280);

    await page.setViewportSize({ width: 320, height: 600 });
    await expect(page.getByRole("heading", { name: "Academia AI Voice Co-Pilot" })).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(320);

    await advanceToApproval(page);
    await page.getByRole("button", { name: "Open Approval Dialog" }).click();
    const dialog = page.getByRole("dialog");
    const bounds = await dialog.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(320);
    await expect(page.getByRole("button", { name: "Reject" })).toBeVisible();
  });

  test("a session request timeout is announced and the user can retry", async ({ page }) => {
    let startRequests = 0;
    await page.route("**/sessions", async (route) => {
      startRequests += 1;
      if (startRequests === 1) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        try {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              sessionId: "late-session",
              status: "active",
              message: "Session started successfully",
            }),
          });
        } catch {
          // The client aborts this deliberately delayed response on timeout.
        }
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          sessionId: "retry-session",
          status: "active",
          message: "Session started successfully",
        }),
      });
    });
    await page.route("**/sessions/*/events**", async (route) => {
      const event = {
        id: 1,
        type: "session",
        payload: { sessionId: "retry-session", status: "active" },
      };
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: `id: 1\ndata: ${JSON.stringify(event)}\n\nevent: replay-complete\ndata: {}\n\n`,
      });
    });
    await page.route("**/sessions/retry-session/events", async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ event: { id: 2 } }),
      });
    });

    await page.goto("/");
    await page.getByRole("button", { name: "Start Session" }).click();
    await expect(page.getByRole("alert")).toContainText("Request timed out");
    await expect(page.getByRole("button", { name: "Start Session" })).toBeEnabled();

    await page.getByRole("button", { name: "Start Session" }).click();
    await expect(page.getByText("Session Status: active")).toBeVisible();
    await expect(page.getByText("Last event received: 1")).toBeVisible();
    expect(startRequests).toBe(2);
  });
});
