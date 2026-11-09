---
name: amazon-seller
description: Amazon.in seller playbook for saree accounts in Seller Desk - orders, stock, ASIN listings and strict content rules.
---

# Amazon.in seller playbook

Use this whenever the user asks about Amazon orders, returns, stock or listings.

## Daily check

1. `get_overview`. Note each account's newest order date.
2. `get_orders` with `status: "pending"` per account, and the oldest pending date. Late shipment hurts account
   health on Amazon, so list anything pending for more than a day.
3. `get_orders` with `days: 30` and status `customer_return`. Report the return count and the SKUs with repeat
   returns.
4. `get_stock_mismatches`. Add a task for each listing that needs updating in Seller Central, or propose a
   master stock change when the user says the Amazon figure is right.
5. `get_listings` per account: count listings without approved content (`has_approved_content: false`) and offer
   to draft content for the top ones.

## Content for Amazon (strict)

- Title at most **75 characters** including spaces. Seller Desk enforces this when you propose.
- Item highlights at most 125 characters.
- No characters `! $ ? _ { } ^ ¬ ¦ ~ # < > * | ; :` in the title, and no word more than twice.
- Up to 5 bullets of 255 characters. Search terms at most 249 bytes, no brand name, no repeats, no commas
  needed.
- Title pattern: Brand + Saree type + Fabric + key feature + Colour, for example
  "Shanthi Women's Kanjivaram Silk Saree with Zari Border and Blouse Maroon".
- Use only facts from `get_product`. Then call `propose_content_draft`.

## Things to remember about Amazon

- Listings are identified by ASIN (`listing_ref` in Seller Desk) and seller SKU (`marketplace_sku`).
- Seller Desk can pull Amazon listing reports through SP-API on the Connections page; suggest a sync when
  listing stock looks old.
- Live figures: call `read_live_panel` for the account; Seller Desk reads the panel tab the user has open.
