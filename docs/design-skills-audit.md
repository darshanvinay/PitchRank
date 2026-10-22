# PitchRank design skills audit — 22 October 2026

This audit preceded the La Liga implementation. Installation and past execution are separate claims.

| Requested skill | Installation and actual instructions read | Responsibility | Previous PitchRank use: evidence |
| --- | --- | --- | --- |
| TasteSkill | `/Users/darshan/.codex/plugins/cache/taste-skill/taste-skill/2.1.4/skills/taste-skill/SKILL.md`, plus `references/app-screens.md` | App-screen art direction, restrained data styling, real-browser inspections at desktop/tablet/mobile, screenshot critique and fixes | Confirmed. `.taste-skill/direction.json` records analytics direction `achromatic-ledger`, seed 1559896174, 22 October 17:55 UTC. `.taste-skill/leaderboard-final/report.json` and `team-final/report.json` contain measured inspections and screenshots, both 0 failures. `docs/mvp-verification.md` records the critique and fixes. |
| web-design-guidelines | `/Users/darshan/.agents/skills/web-design-guidelines/SKILL.md` | Fetch current Vercel Web Interface Guidelines, inspect frontend code, report file/line findings; semantics, accessibility, focus, responsiveness, URL state, theme and performance | Previous conversation tool history records the skill and source guidelines being read; `docs/mvp-verification.md` records the resulting checks. No separate machine-generated historical audit exists, so the evidence is less extensive than TasteSkill's reports. |
| AwesomeDesign | No single `AwesomeDesign/SKILL.md`. The installed collection is **bergside/awesome-design-skills**, recorded for 67 styles in `/Users/darshan/.agents/.skill-lock.json`. Relevant accessible instructions read: `/Users/darshan/.agents/skills/clean/SKILL.md`. | Design-system consistency: semantic tokens, spacing, explicit component states, clarity, WCAG 2.2 AA, keyboard access, reduced motion and 44px touch targets | **Not established.** Availability and the user's earlier request do not prove execution. No prior style-selection or application artifact was found. Applied `clean` consistency/accessibility guidance explicitly during this extension. |

An earlier search for a standalone AwesomeDesign file missed the installed collection. The corrected status is installed and accessible as individual styles, not absent. Only the relevant `clean` SKILL.md is claimed as read/applied, not every style in the collection.

## How the skills apply to this extension

Intent: switching competitions should feel like another scope of the same PitchRank workspace.
Reuse the existing Geist font, neutral dark surfaces, semantic CSS tokens, table density, crest identities and blue Elo chart. Do not import the Clean skill's illustrative Roboto/Poppins palette, because the user's explicit instruction preserves the existing identity. No new art direction was drawn: this is a component extension, not a redesign. Keep the original direction/seed for traceability.

TasteSkill: use its **app-screen** workflow, not landing-page photography, hero or motion rules. The first question remains “Which clubs are strongest in this league?”; team pages answer “How did this club's strength change?” Real club crests and match-derived Elo movement remain the signature elements. No sample data is displayed.

Web Interface Guidelines were freshly fetched from https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md for the current review. Apply native named/labelled selects, keyboard and visible-focus support, URL-backed league selection, cancellation of stale league fetches, and loading/error feedback. Keep league identity on all links and refresh requests.

AwesomeDesign Clean: use existing tokens and spacing; ensure consistent selector/refresh/navigation states, honest error/loading states and 44px mobile controls. Validate touch targets and responsive overflow in a real browser.

## Existing issues found before changes

Historical line numbers refer to the pre-extension source.

- `frontend/src/style.css:1083` — mobile nav rows were 40px; theme controls 38–40px, below the 44px touch guidance in TasteSkill/Clean. Raised relevant mobile controls to 44px.
- `frontend/src/style.css:1128` — mobile Method link replaced its text with generated CSS content and font-size zero. Replaced with explicit responsive text spans, so its visible and accessible names agree.
- `frontend/src/style.css` — team statistics' rightmost mobile label was 12px from the edge, below the app-screen 16–20px margin guidance. Fixed the mobile grid minimum widths and wrapped long labels, keeping the total inside its panel.
- `frontend/src/App.tsx:457` — existing filter controls already have names, labels and autocomplete handling. New league selector must meet the same standard.
- `.taste-skill/laliga-before/report.json` — 51% of measured text under 13px. Core table data remains 13–14px; compact table headings, form codes and metadata remain 11–12px as an intentional dense-table compromise. This is a warning, not a claim of full large-text compliance.
- `.taste-skill/laliga-before/report.json` — low-data-hue warning on leaderboard. Thin blue rating marks are retained; team history already uses the blue line. Changing the palette or adding decorative panels would conflict with the preservation request.

Existing strengths retained: semantic links/buttons/tables, skip link, explicit crest dimensions, self-hosted fonts, labelled chart with an accessible data table, locale-aware dates/currency, reduced-motion handling, dark color-scheme, status live region, URL-backed filters, contained mobile table scrolling and pinned identity column.

See `docs/laliga-verification.md` for final tests, screenshots, remaining warnings and the current review locations.
