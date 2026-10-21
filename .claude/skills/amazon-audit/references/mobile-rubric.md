# Mobile rubric

Most Amazon shopping happens on the app or mobile web. On a phone:
- search results show a small thumbnail and roughly the first 80 characters of the title
- the gallery is swiped full-width at about 375px
- bullets sit collapsed under "About this item"
- A+ modules stack full-width, so text baked into images shrinks

`analyse/mobile.py` scores every best-seller. Keep the thresholds here and in the code in step.

| Check | Good | Warn | Fail | Why it matters on mobile |
|---|---|---|---|---|
| Zoom | all images ≥1600px | 1000–1599px | any <1000px (zoom disabled) | Shoppers pinch to inspect texture, ingredients and size |
| Images | 7+ | 5–6 | <5 | Swiping the gallery is the main way people explore a product on mobile |
| Video | brand-made video ≤90s | only influencer/customer videos, or long brand video | none | A short brand video near the top of the gallery explains the product faster than text |
| Title in search | brand, product type and size in the first 80 characters | brand or size cut off | product type cut off | People choose from truncated titles in mobile search |
| Bullets | all ≤250 characters | some longer | none | Collapsed bullets need to land in the first line |
| A+ on a phone | text is light | 1–2 text-heavy images (>30 words) | 3+ text-heavy, or no A+ | Copy inside stacked images becomes unreadably small |

## Legibility review (needs `m.media-amazon.com` in Allowed domains)
When `heroes[].mobile_sheet` exists, open the PNG. It shows the main image at search-thumbnail size and
every gallery image at phone width. For each best-seller, judge:
- **The thumbnail:** can you tell what the product is and its pack size at 150px? Does the product fill the frame?
- **Callouts:** can every callout be read at phone width without zooming? More than 3–4 callouts per image is too many.
- **The worst image:** name it, e.g. "PT03 ingredient panel".

Write `findings.mobile_review[asin] = {"legible": true|false, "worst_image": "...", "verdict": "one line"}`.
Without a sheet, base the verdict on the A+ text-density check and say legibility wasn't checked.

## How to use it in the pitch
- Fails on a best-seller are strong, concrete email bullets. For example: "Your top seller has no brand video,
  only influencer clips" or "Half your A+ images are unreadable on a phone".
- Group mobile issues into one point unless one alone is the biggest lever.
