import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("clean load has no browser errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));

  await page.reload();
  await page.waitForLoadState("networkidle");
  expect(errors).toEqual([]);
});

test("product tabs support roving keyboard navigation", async ({ page }) => {
  const tabs = page.getByRole("tab");
  await expect(tabs).toHaveCount(4);

  await tabs.nth(0).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.nth(1)).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel", { name: "Room Shell" })).toBeVisible();

  await page.keyboard.press("End");
  await expect(tabs.nth(3)).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel", { name: "Swap" })).toBeVisible();

  await page.keyboard.press("Home");
  await expect(tabs.nth(0)).toHaveAttribute("aria-selected", "true");
});

test("Room Type select has the shared visible keyboard focus ring", async ({ page }) => {
  const select = page.locator(".hero-control select");
  await select.focus();
  const focusStyle = await select.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      focused: document.activeElement === element,
      outlineColor: style.outlineColor,
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
    };
  });

  expect(focusStyle).toEqual({
    focused: true,
    outlineColor: "rgb(68, 107, 206)",
    outlineStyle: "solid",
    outlineWidth: "3px",
  });
});

test("sample dialog changes Variant and swaps an equal-footprint fixture in place", async ({ page }) => {
  const trigger = page.getByRole("button", { name: "Explore a sample Design" }).first();
  await trigger.click();

  const dialog = page.getByRole("dialog", { name: "Sample Design" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("Illustrative furnishings; no live Catalogue or room generation.");

  const fixture = dialog.getByTestId("swap-fixture");
  const fixtureBefore = await fixture.evaluate((node) => {
    const group = node as unknown as SVGGElement;
    const box = group.getBBox();
    return {
      markup: group.innerHTML,
      transform: group.getAttribute("transform"),
      box: { x: box.x, y: box.y, width: box.width, height: box.height },
    };
  });
  await expect(dialog.getByText("4.0 × 3.0m Room Shell · Variant A")).toBeVisible();

  await dialog.getByRole("button", { name: "B", exact: true }).click();
  await expect(dialog.getByText("4.0 × 3.0m Room Shell · Variant B")).toBeVisible();
  await expect(fixture).toHaveAttribute("transform", fixtureBefore.transform ?? "");

  await dialog.getByRole("button", { name: "Swap to Cove chair" }).click();
  await expect(dialog.getByText("Cove chair", { exact: true }).last()).toBeVisible();
  const fixtureAfter = await fixture.evaluate((node) => {
    const group = node as unknown as SVGGElement;
    const box = group.getBBox();
    return {
      markup: group.innerHTML,
      transform: group.getAttribute("transform"),
      box: { x: box.x, y: box.y, width: box.width, height: box.height },
    };
  });
  expect(fixtureAfter.markup).not.toBe(fixtureBefore.markup);
  expect(fixtureAfter.transform).toBe(fixtureBefore.transform);
  expect(fixtureAfter.box).toEqual(fixtureBefore.box);

  await dialog.getByLabel("Room Type").selectOption("bedroom");
  await expect(dialog.getByRole("img", { name: /illustrative bedroom concept/i })).toBeVisible();

  await dialog.getByRole("button", { name: "Close sample" }).click();
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();

  await trigger.click();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("every bedroom Variant keeps the bed clear of the fixed chair slot", async ({ page }) => {
  await page.getByRole("button", { name: "Explore a sample Design" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Sample Design" });
  await dialog.getByLabel("Room Type").selectOption("bedroom");

  type Bounds = { left: number; right: number; top: number; bottom: number };
  let fixedChair: Bounds | undefined;

  for (const variant of ["A", "B", "C"]) {
    await dialog.getByRole("button", { name: variant, exact: true }).click();
    const bounds = await dialog.locator("svg").evaluate((svg) => {
      const transformedBounds = (element: SVGGraphicsElement) => {
        const box = element.getBBox();
        const matrix = element.getCTM();
        if (!matrix) throw new Error("Expected an SVG transform matrix");
        const points = [
          new DOMPoint(box.x, box.y),
          new DOMPoint(box.x + box.width, box.y),
          new DOMPoint(box.x, box.y + box.height),
          new DOMPoint(box.x + box.width, box.y + box.height),
        ].map((point) => point.matrixTransform(matrix));
        const xs = points.map((point) => point.x);
        const ys = points.map((point) => point.y);
        return { left: Math.min(...xs), right: Math.max(...xs), top: Math.min(...ys), bottom: Math.max(...ys) };
      };
      const bed = svg.querySelector<SVGGraphicsElement>(".furnishing--bed");
      const chair = svg.querySelector<SVGGraphicsElement>(".swap-fixture");
      if (!bed || !chair) throw new Error("Expected bedroom bed and chair SVG groups");
      return { bed: transformedBounds(bed), chair: transformedBounds(chair) };
    });

    const overlaps = bounds.bed.left < bounds.chair.right
      && bounds.bed.right > bounds.chair.left
      && bounds.bed.top < bounds.chair.bottom
      && bounds.bed.bottom > bounds.chair.top;
    expect(overlaps, `Bedroom Variant ${variant} bed must clear the chair`).toBe(false);
    if (fixedChair) expect(bounds.chair).toEqual(fixedChair);
    else fixedChair = bounds.chair;
  }
});

test("mobile navigation closes with Escape and after selecting an anchor", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();

  const menuButton = page.getByRole("button", { name: /Product · How it works · FAQ/ });
  await menuButton.click();
  const menu = page.getByRole("navigation", { name: "Mobile navigation" });
  await expect(menu).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(menuButton).toHaveAttribute("aria-expanded", "false");

  await menuButton.click();
  await menu.getByRole("link", { name: "FAQ" }).click();
  await expect(menu).toBeHidden();
  await expect(page).toHaveURL(/#faq$/);
});

test("every in-page link resolves to an existing unique target", async ({ page }) => {
  const report = await page.locator('a[href^="#"]').evaluateAll((anchors) => {
    const hrefs = anchors.map((anchor) => anchor.getAttribute("href") ?? "");
    return hrefs.map((href) => ({
      href,
      count: document.querySelectorAll(href).length,
    }));
  });

  expect(report.length).toBeGreaterThan(0);
  for (const target of report) expect(target.count, target.href).toBe(1);
});

for (const width of [390, 639, 640, 768, 900, 901, 1440, 1535, 1536, 1920]) {
  test(`content frame and unframed navigation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const layout = await page.evaluate(() => {
      const header = document.querySelector<HTMLElement>(".site-header")!;
      const hero = document.querySelector<HTMLElement>(".hero")!;
      const row = document.querySelector<HTMLElement>(".header-main")!;
      const bounds = (element: HTMLElement) => {
        const rect = element.getBoundingClientRect();
        return { x: rect.x, width: rect.width };
      };
      const style = getComputedStyle(header);
      return {
        header: bounds(header), hero: bounds(hero), row: bounds(row),
        borders: [style.borderLeftWidth, style.borderRightWidth],
      };
    });
    const frameWidth = width <= 639 ? width : Math.min(width * 0.9, width >= 1536 ? 1440 : 1280);
    expect(layout.header).toEqual({ x: 0, width });
    expect(layout.borders).toEqual(["0px", "0px"]);
    expect(layout.hero.width).toBeCloseTo(frameWidth, 1);
    expect(layout.hero.x).toBeCloseTo((width - frameWidth) / 2, 1);
    expect(layout.row.width).toBeCloseTo(frameWidth, 1);
    expect(layout.row.x).toBeCloseTo(layout.hero.x, 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}

// Preserve all eight accepted heading-overflow checks. The added 900/901 frame
// probes above preserve their layout without changing the inherited 901px heading.
for (const width of [390, 639, 640, 768, 1440, 1535, 1536, 1920]) {
  test(`page has no horizontal overflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.reload();
    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);

    const overflowingHeadings = await page.locator("h1, h2, h3").evaluateAll((headings) => headings
      .filter((heading) => {
        const style = getComputedStyle(heading);
        return !heading.classList.contains("sr-only") && style.display !== "none" && style.visibility !== "hidden" && heading.getClientRects().length > 0;
      })
      .filter((heading) => heading.scrollWidth > heading.clientWidth + 2)
      .map((heading) => ({ text: heading.textContent, scrollWidth: heading.scrollWidth, clientWidth: heading.clientWidth })));
    expect(overflowingHeadings).toEqual([]);
  });
}

test("reduced motion preference disables smooth scrolling", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  const scrollBehavior = await page.locator("html").evaluate((element) => getComputedStyle(element).scrollBehavior);
  expect(scrollBehavior).toBe("auto");
});
