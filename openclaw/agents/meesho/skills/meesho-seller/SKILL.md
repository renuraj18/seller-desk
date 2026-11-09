---
name: meesho-seller
description: Meesho seller playbook for saree accounts in Seller Desk - orders, returns and RTO, stock sync and catalogue content.
---

# Meesho seller playbook

Use this whenever the user asks about Meesho orders, returns, stock or listings.

## Daily check (when the user says "check Meesho" or similar)

1. `get_overview`. Note each account's newest order date.
2. `get_orders` with `status: "pending"` for each account that has pending orders. Report counts per account.
3. `get_orders` with `days: 7` and status `courier_return` and `customer_return`. Meesho sellers lose most money
   on RTO and returns, so call out any SKU with two or more returns in the week.
4. `get_stock_mismatches`. For each row, propose a fix only when the right figure is clear:
   - If the master stock is right and Meesho shows a different number, add a task: "Update stock for <SKU> on
     <account> in the Meesho supplier panel to <master>".
   - If the user tells you the Meesho figure is right, use `propose_master_stock`.
5. Finish with a short table: account, pending, returns this week, charges, mismatches.

## Content for Meesho

- Title up to 100 characters. No highlights field. Up to 5 bullets of 255 characters.
- Meesho buyers search in simple words: fabric + saree type + colour + occasion, for example
  "Cotton Silk Saree Maroon Zari Border Wedding".
- Do not use brand names you are not given, and never use words like "original", "100%", "best" or
  "guaranteed". Seller Desk also removes blocked words when you propose.
- Call `get_product` first, then `propose_content_draft` with the facts it returns.

## Things to remember about Meesho

- Meesho shows cancel and return charges per order; Seller Desk keeps them in `cancel_charges` and
  `return_charges`. Report them separately from sales.
- Orders reach Seller Desk from imported files or the browser extension, so data can lag. Always state the
  newest order date.
- Live figures: call `read_live_panel` for the account; Seller Desk reads the panel tab the user has open.
