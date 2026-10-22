# Shared Elo scale — 22 October 2026

The previous league-median prior made equal euro squad values start at different ratings. Replaced it with one fixed, configurable reference, shared by every supported league:

```
starting Elo = 1500 + clip(60 × ln(value_eur / 556425000), −100, +100)
```

€556,425,000 is the median of the existing, sourced Premier League September 2026 snapshot. It is a frozen reference point, **not** a claimed median for Europe's top five leagues. This choice preserves the existing EPL numerical ratings while removing league-specific initialization. It does not change when another league is imported or another squad value is corrected. `SQUAD_REFERENCE_EUR` can change it deliberately; doing so invalidates all old calculation fingerprints and requires recalculating each league.

Same exact squad value now gives the same initial rating in any league. City (€1.33bn) starts at 1552.2841; Barcelona (€1.26bn) starts at 1549.0401. Their UI totals previously both rounded to €1.3bn, but their underlying values are different. Barcelona's recalculated current rating is 1625.1313; City's remains 1613.3250. All completed matches and stored squad values are retained; both season histories are recalculated from the new prior with unchanged K, home advantage, goal-margin multiplier and cap.

Matches remain scoped to their own league and season. No extra leagues, models, prediction algorithms or services were added. A future supported league must use the same reference and parameters.

## Comparison limitation

The scale is now numerically consistent, but comparisons between leagues are **anchored by market values only**. Domestic matches form disconnected groups: they cannot establish which league is stronger or correct a misleading league-wide valuation prior. A calibrated European ranking would need verified cross-league competitive results (for example UEFA club matches) tying these groups together. That is not silently claimed or implemented here. No invented league-strength coefficients are used. Different match counts also mean different amounts of performance evidence; they do not earn automatic Elo bonuses.

The Method page explains both the shared reference and this limitation. The installed TasteSkill app-screen guidance, Web Interface Guidelines and AwesomeDesign Clean consistency guidance apply to the copy change; layout, theme and typography are preserved.

Verification: equal-value clubs in different squad distributions get equal starting ratings; adding another club cannot move an existing club's prior; neutral missing-value fallback retained; reference must be positive and finite; updated shared-engine integration assertions. Both current leagues were replayed and the EPL numerical before/after snapshot compared exactly.
