// Record splitting a restaurant bill six ways, each person paying for their own meal.
//
//   node rec-restaurant-bill.js <out dir>
//
// Maya creates the event, adds five friends by name (none of them needs an
// account), logs the dinner split by item with shared appetizers, tax and a
// tip on the total after tax, and ends on the overview showing who owes her.
// MOBILE=1 records at phone width.
const L = require("./lib");
const S = L.CONFIG.base;
const OUT = process.argv[2] || "video-restaurant-bill";

const FRIENDS = ["Lena", "Omar", "Priya", "Jonas", "Sofia"];
const MEALS = {
  Maya: "24.00",
  Lena: "31.50",
  Omar: "18.00",
  Priya: "27.00",
  Jonas: "22.50",
  Sofia: "19.00",
};

(async () => {
  const launched = await L.launch({ record: OUT });
  const { page } = launched;
  const cap = (t) => L.caption(page, t);

  try {
    await L.login(page);
    await page.goto(S + "/expenses/");
    await L.sleep(500);
    await cap("Six friends had dinner. Maya paid the bill.");
    await L.sleep(2200);

    // The event
    await cap("Start an event for the dinner");
    await L.click(page, 'a:has-text("+ New event")');
    await L.type(page, 'input[name="name"]', "Lena's birthday dinner");
    await L.click(page, '#id_start_date ~ .sc-today-button', { pause: 400 });
    await L.click(page, 'button:has-text("Create event")', { pause: 1200 });

    // The people
    await cap("Add the other five. A name is enough: nobody needs an account.");
    await L.click(page, 'a:has-text("People")', { pause: 900 });
    const add = page.locator('[data-add-row]');
    for (let i = 0; i < FRIENDS.length; i++) {
      if (i >= (await page.locator('[data-bulk-rows] [data-bulk-row]').count())) {
        await L.click(page, add, { pause: 300 });
      }
      await L.type(page, `input[name="people-${i}-display_name"]`, FRIENDS[i]);
    }
    await L.sleep(400);
    await L.click(page, 'button[type="submit"]:has-text("Add people")', { pause: 1200 });
    await L.sleep(1200);

    // The bill
    await L.click(page, '.breadcrumb a:has-text("Lena")', { pause: 900 });
    await cap("Log the bill, split by what each person ate");
    await L.click(page, 'a:has-text("Log expense")', { pause: 800 });
    await L.type(page, 'input[name="description"]', "Dinner at Trattoria Nonna");
    await L.choose(page, 'select[name="category"]', "Food");
    await L.click(page, 'input[name="split_mode"][value="itemized"]', { pause: 600 });

    await cap("Everyone's own meal");
    for (const [name, amount] of Object.entries(MEALS)) {
      const row = page.locator("tr[data-participant]", { hasText: name });
      await L.type(page, row.locator('input[name^="item_"]'), amount, { delay: 40 });
    }

    await cap("Two appetizers everyone shared");
    await L.type(page, 'input[name="shared_amount"]', "16");
    await cap("Sales tax, then a 20% tip on the total after tax");
    await L.type(page, 'input[name="tax_percent"]', "8.875");
    await L.type(page, 'input[name="tip_percent"]', "20");

    await L.scrollToTop(page, 'th:has-text("Shared by")');
    await cap("Each person's share, with their part of the extras");
    await L.sleep(3500);

    await L.click(page, 'button[type="submit"]:has-text("Save")', { pause: 1200 });
    await cap("Saved. The ledger shows what each person owes.");
    await L.sleep(3000);

    await L.click(page, '.breadcrumb a:has-text("Lena")', { pause: 900 });
    await cap("And the overview shows who pays Maya back");
    await L.scrollToTop(page, 'h2:has-text("Balances")');
    await L.sleep(4000);
    await L.caption(page, "");
    await L.sleep(500);
  } finally {
    await L.finish(launched);
  }
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
