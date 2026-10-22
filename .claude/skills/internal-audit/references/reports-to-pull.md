# Reports to pull

Set the marketplace selector (top bar, "United States ▼") before every export. Upload CSV or XLSX as they come;
file names don't matter, `analyse/internal_audit.py` recognises each report by its columns.

## Amazon Ads console
**Where:** left menu → Measurement & Reporting → Sponsored ads reports → **Create report**.

Settings for each: Category as listed, Time unit **Daily** where offered (Summary is fine for the rest),
Report period = the last 60 days or since the campaigns launched, Delivery = Run now → **Run report**.

| Report | Category | Needed for |
|---|---|---|
| Advertised product (**Daily**) | Sponsored Products | ad spend, orders and units per ASIN and week; TACoS; spend vs rank |
| Search term | Sponsored Products | spend and orders per shopper search; spend by search type |
| Targeting | Sponsored Products | which searches are actual keywords; top-of-search share per keyword |
| Placement | Sponsored Products | top of search vs rest of search vs product pages |
| Search term (optional) | Sponsored Brands | video/headline spend by search |

Status "**Pending**" means it's queued: don't click Run report again, refresh in a few minutes. When Last run shows
a date, the ↓ icon downloads it. Amazon also emails a link.

**Campaign list:** Campaign manager → Campaigns, same date range → **Export** (or a screenshot). Gives budgets,
bid strategy, top-of-search adjustment and Sponsored Brands spend.

## Seller Central
The newer menu has no "Reports" item. Use the search box at the top of the ☰ menu.

**Business Reports** (search "Business Reports", or go to `sellercentral.amazon.com/business-reports`):
left panel → By ASIN → **Detail Page Sales and Traffic by Child Item** → set dates → Apply → Download (.csv).
It sums the whole range, so download one file per period (e.g. last month and month-to-date) and note the dates.
Download with all ASINs; the script picks the product out.

**Search Query Performance** (search "Brand Analytics" or "Search Query Performance"):
switch to **ASIN View** → enter the ASIN → Reporting range **Weekly** → pick a week → Apply →
**Generate Download** → Current view → CSV → collect it from the **Downloads Manager**. Repeat for 6–7 weeks.
Needs Brand Registry rights; a distributor login may not see it.

**Optional:** the same Business Report for the product in another marketplace, as a conversion benchmark.
