from playwright.sync_api import sync_playwright
import json

URL = "https://www.thaiwater.net/water/wl"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 3000}
        )
        page = context.new_page()

        # Block heavy resources for speed
        page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in ["image", "media", "font"]
            else route.continue_(),
        )

        page.goto(URL, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_selector("tr.MuiTableRow-root", timeout=60000)

        all_rows = []
        page_no = 1

        while True:
            rows_data = page.evaluate(r"""
            () => {
              const clean = s => (s || "").replace(/\s+/g, " ").trim();

              return Array.from(document.querySelectorAll("tr.MuiTableRow-root")).map(r => {
                const station = clean(r.querySelector("th span.MuiButton-label")?.textContent);
                const tds = Array.from(r.querySelectorAll("td"));

                const title = tds[6]?.querySelector("button")?.getAttribute("title") || "";
                let trend = "UNKNOWN";
                if (title.includes("เพิ่มขึ้น")) trend = "UP";
                else if (title.includes("ลดลง")) trend = "DOWN";
                else if (title.includes("ทรงตัว")) trend = "STABLE";

                return {
                  station_name: station,
                  river: clean(tds[0]?.textContent),
                  location: clean(tds[1]?.textContent),
                  water_level: clean(tds[2]?.textContent),
                  bank_level: clean(tds[3]?.textContent),
                  status: clean(tds[4]?.querySelector("div.MuiBox-root")?.textContent),
                  trend,
                  update_time: clean(tds[7]?.textContent),
                };
              });
            }
            """)

            all_rows.extend(rows_data)

            # Progress indicator (safe, minimal)
            print(f"PAGE {page_no}: +{len(rows_data)} (TOTAL {len(all_rows)})")

            next_btn = page.locator("button[aria-label='Next Page']")
            if next_btn.count() == 0 or next_btn.is_disabled():
                break

            displayed = page.locator("p.MuiTablePagination-displayedRows")
            displayed_before = displayed.inner_text() if displayed.count() else ""

            next_btn.click(force=True)

            if displayed.count():
                page.wait_for_function(
                    """(prev) => {
                        const el = document.querySelector("p.MuiTablePagination-displayedRows");
                        return el && el.textContent && el.textContent.trim() !== (prev || "").trim();
                    }""",
                    arg=displayed_before,
                    timeout=60000,
                )
            else:
                page.wait_for_timeout(500)

            page_no += 1

        browser.close()
        return all_rows
        

if __name__ == "__main__":
    data = main()

    # Save to JSON (Thai-safe)
    output_file = "thaiwater_wl.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ DONE: saved {len(data)} rows to {output_file}")