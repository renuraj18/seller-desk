---
name: flipkart-seller
description: Flipkart seller playbook for saree accounts in Seller Desk - orders, returns, listing status and content.
---

# Flipkart seller playbook

Use this whenever the user asks about Flipkart orders, returns, stock or listings.

## Daily check

Call `get_daily_check` first. Seller Desk has already worked out pending, overdue and no-stock orders, returns and how
fresh the data is from the browser extension's sync. Report from it; use the other tools only for detail. Add an
`add_task` for each item only the user can do (sign in again, dispatch overdue orders, fix a stock gap).


1. `get_overview`. Note each account's newest order date.
2. `get_orders` with `status: "pending"` per account: these need dispatch before the SLA. Report counts and the
   oldest pending order date per account.
3. `get_orders` with `days: 7` and status `courier_return` and `customer_return`. Flag SKUs with repeat returns
   and suggest checking photos, colour accuracy and size details for them.
4. `get_stock_mismatches`. Out-of-stock live listings lose ranking on Flipkart, so put rows where the account
   shows 0 and master shows stock first. Add a task for the user to update stock in Seller Hub.
5. `get_listings` with `status: "rejected"` for each account. For each rejected listing, check its content with
   `get_product` and propose better content if that is the likely cause.

## Content for Flipkart

- Title up to 100 characters: brand, saree type, fabric, colour, key work, for example
  "Shanthi Kanjivaram Silk Saree with Zari Border and Blouse Piece (Maroon)".
- No highlights field. Up to 5 bullets of 255 characters. Description in plain sentences.
- Use only facts from `get_product`. Never claim "pure silk" or "handloom" unless the product data says so.
- Propose with `propose_content_draft`; Seller Desk trims it to the limits and removes blocked words.

## Things to remember about Flipkart

- Listings are identified by FSN / listing ID (`listing_ref` in Seller Desk).
- Seller Desk can also sync Flipkart listings through the API on the Connections page; if listing stock looks
  old, suggest running a sync there.
- Live figures: call `read_live_panel` for the account; Seller Desk reads the panel tab the user has open.
