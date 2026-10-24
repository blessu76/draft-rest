# Blog queue — status

Daily post at 16:00 KST. Each post = `posts/<slug>/ko.md` (canonical) + `en.md` + `translations/<lang>.md` (ja zh es pt id ru vi fr de) — all 11 languages present.

| # | Publish date (KST) | Slug | Topic | Status |
|---|--------------------|------|-------|--------|
| 1 | 2026-10-23 | `blank-caption-box` | Stuck at the blank caption box? Talk first | published (main) |
| 2 | 2026-10-24 | `thirty-second-practice` | 30-second drill: pick one scene | queued (draft) |
| 3 | 2026-10-25 | `first-line-hook` | One first line can save a story (hook) | queued (draft) |
| 4 | 2026-10-26 | `ending-without-a-moral` | End on an echo, not a moral | queued (draft) |
| 5 | 2026-10-27 | `nothing-happened-today` | Finding a story in "nothing happened" | queued (draft) |

Queued dates are placeholders; `publish_post.py` stamps the real date and time. Facts about draft() are limited to what the site states
(talk ~30 s → 2–3 gentle questions → story hook/rising/peak/reflection/close; privacy; no claims about release or formats).

## Publish one post (daily, ~16:00 KST)

```
python3 scripts/publish_post.py <slug>          # removes `draft: true`, sets date + `published` = now (KST) in all 11 files
python3 scripts/build_site.py                   # writes pages, feeds, sitemap.xml, llms.txt (re-run build_site.py --check afterwards)
python3 scripts/check_sitemap.py
python3 -m unittest discover -s tests
git add -A && git commit && push main          # GitHub Actions deploys; then: python3 scripts/indexnow.py <new urls> (key file is committed at the site root)
```

- Run publish_post.py right before the commit that is pushed — never pre-stamp a planned time. If the push slips, re-run `scripts/stamp_published.py <slug>`.
- Posts dated 2026-10-24 or later must carry `published` (ISO time with +09:00 offset, same in all 11 files, same KST day as `date`); the build fails without it.
- The page shows `// YYYY-MM-DD HH:MM` (KST) from `published`.
- Update the table above when a post goes live (status → published).
