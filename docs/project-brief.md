# Build a Premier League Elo Rating & Match Prediction Platform

## 1. Project Overview

Build a production-quality, full-stack football analytics platform focused exclusively on the English Premier League (EPL).

The application should maintain Elo ratings for every Premier League club, automatically update those ratings as matches finish, and predict home-win, draw, and away-win probabilities for upcoming fixtures.

The platform should also provide interactive football analytics, historical team rating trends, and a comprehensive backtesting dashboard that measures the accuracy of its predictions.

**Primary goal:** Create a technically impressive, reliable, maintainable, and visually polished software engineering portfolio project suitable for competitive SWE internship applications.

This must be a genuinely functional analytics platform, not a frontend demonstration with hardcoded football statistics.

All ratings, predictions, match results, charts, and evaluation metrics must originate from real data and the implemented prediction engine.

## 2. Technology Stack

### Backend
- Python 3.12+
- FastAPI for REST API endpoints
- SQLite for persistent storage
- SQLAlchemy for database access
- Alembic for database migrations
- Pydantic for validation and API schemas
- APScheduler or a separate scheduled worker for automated match updates
- pytest for unit and integration testing

### Data Science and Mathematical Modeling
- **Pandas:** Import, clean, normalize, and analyze historical Premier League CSV datasets.
- **NumPy:** Perform numerical calculations, evaluate probability predictions, calculate Brier scores and log loss, and support efficient statistical analysis.
- **SciPy:** Optimize Elo parameters and prediction-model parameters using historical data.
- **Matplotlib:** Generate analytical visualizations for backtesting, probability calibration, and model comparisons.

### Frontend
- React
- TypeScript
- Tailwind CSS
- Recharts for interactive frontend graphs
- React Router for navigation

Use Vite unless there is a compelling technical reason to use another frontend build system.

### Developer Tools
- Git and GitHub
- GitHub Actions for automated tests and linting
- Ruff for Python linting and formatting
- ESLint for frontend code quality
- Environment variables for secrets and configuration

Avoid unnecessary dependencies.

## 3. Historical Football Data

Use historical English Premier League match results from football-data.co.uk.

Import multiple seasons of historical data to establish meaningful Elo ratings and train and evaluate the prediction model.

The historical data ingestion pipeline must:

1. Download or load historical Premier League CSV files.
2. Use Pandas to clean and normalize the datasets.
3. Standardize dates, team names, scores, and season identifiers.
4. Validate required fields and reject invalid records with useful error messages.
5. Convert dates to consistent internal representations.
6. Store validated matches in SQLite.
7. Prevent duplicate imports.
8. Support re-importing datasets without corrupting existing records.
9. Preserve source information for debugging and auditing.

### Team Identity Management

Create a canonical teams table with unique internal identifiers.

Different data providers may use different names for the same team, such as "Man United" and "Manchester United FC".

Create a centralized team-name mapping system so these names resolve to the same internal team.

Do not rely on raw team-name strings as database identities.

Unknown team names must be flagged for review rather than silently assigned to an incorrect club.

## 4. Database Architecture

Design a normalized SQLite database using SQLAlchemy and Alembic.

At minimum, support the following entities.

### Teams
- Internal team ID
- Canonical team name
- Display name
- Optional crest URL or asset reference
- Relevant metadata

### Team Aliases
- Alias ID
- Team ID
- Data source
- Source-specific team name or identifier

### Matches
- Internal match ID
- External source ID, if available
- Data source
- Match date and kickoff time, where available
- Season
- Home team ID
- Away team ID
- Home goals
- Away goals
- Match status
- Processed flag
- Created and updated timestamps

### Rating History
- Rating history ID
- Match ID
- Team ID
- Rating before match
- Rating after match
- Rating change
- Timestamp or chronological sequence

### Model Configuration / Versions

Store or identify the model configuration used to generate ratings and predictions.

Ensure historical rating records can be associated with the correct model configuration.

Implement appropriate primary keys, foreign keys, indexes, and uniqueness constraints.

Use database transactions for operations that must succeed or fail together.

Handle duplicate matches across data sources using stable match identity rules rather than relying only on provider-specific match IDs.

## 5. Elo Rating Engine

Implement the Elo rating engine as an independent Python module with pure, testable mathematical functions.

### Initial Ratings

- Default starting rating: 1500.
- Promoted clubs should start at the average rating of the relegated clubs from the previous season, or a configurable default such as 1400.
- Define clear rules for clubs returning after multiple seasons outside the EPL.
- Allow configurable season-to-season regression toward the mean.
- Keep all parameters centralized in a configuration file.

### Expected Score

Use the Elo expected-score formula with home-field advantage:

E_home = 1 / (1 + 10^((R_away - R_home - HFA) / 400))

Where:
- R_home = home team's current Elo rating
- R_away = away team's current Elo rating
- HFA = configurable home-field advantage

For Elo rating updates, use actual match scores of 1 for a win, 0.5 for a draw, and 0 for a loss.

### Rating Updates

Use a configurable K-factor and goal-difference multiplier.

A possible multiplier is based on:

ln(|goal_difference| + 1)

Ensure the multiplier is defined sensibly for draws and does not cause a zero update when an update should occur.

Calculate each team's rating change based on the difference between actual and expected outcomes.

The standard two-team match update should be zero-sum, meaning one team's rating gain equals the other team's rating loss.

### Chronological Processing

- Process matches in deterministic chronological order.
- Use kickoff timestamps when available.
- Define a stable ordering rule when timestamps are missing or matches share a date.
- Never process the same match twice.
- Record rating changes for both clubs after each match.
- Support a complete recomputation from historical match records.
- If a historical match result is corrected, rebuild affected rating history consistently.
- Ensure recomputation is transactional and cannot leave partial ratings after failure.

### Model Versioning

Avoid mixing ratings generated with different Elo configurations.

If parameters change, recompute ratings using the new configuration and identify the resulting model version.

## 6. Match Prediction Engine

Implement a prediction engine that calculates probabilities for three possible outcomes:

- Home win
- Draw
- Away win

Use current Elo ratings, home advantage, and a statistically fitted draw model.

The Elo expected score is not automatically equivalent to home-win probability.

Explicitly account for draws when converting Elo differences into three-outcome probabilities.

Fit the draw model using historical data. A logistic or ordered-logit-inspired approach is acceptable if mathematically justified.

Requirements:

1. All probabilities must be between 0 and 1.
2. Home-win, draw, and away-win probabilities must sum to 1.
3. Predictions must use only information available before the fixture.
4. The model must work for any two supported EPL clubs.
5. Predictions must distinguish home and away fixtures.
6. Provide a short, understandable explanation of the factors influencing each prediction.
7. Never describe probabilities as guaranteed outcomes.

Keep prediction logic separate from the Elo rating update engine.

## 7. Parameter Optimization

Use SciPy to optimize model parameters against historical results.

Optimize parameters such as:

- K-factor
- Home-field advantage
- Relevant goal-difference multiplier parameters
- Draw-model parameters
- Season regression parameters, if justified

Use multiclass log loss as the primary optimization objective.

Use sensible parameter bounds to prevent unrealistic values.

Do not tune parameters on the final test seasons.

Use chronological training and validation splits.

Because Elo updates are sequential, the optimization process must replay matches in order whenever parameter changes affect historical ratings.

Avoid information leakage.

Store the optimized parameters and make results reproducible with a fixed configuration and documented dataset.

## 8. Backtesting and Model Evaluation

Build a comprehensive walk-forward backtesting system.

### Walk-Forward Evaluation

For each match in the evaluation period:

1. Obtain both teams' ratings using only earlier available results.
2. Generate home-win, draw, and away-win probabilities.
3. Save the prediction.
4. Compare the prediction with the actual match outcome.
5. Update Elo ratings using the actual result.
6. Continue to the next match.

Use separate historical periods for training, validation, and final testing.

For matches with ambiguous ordering or missing kickoff times, use a conservative policy that prevents future information from entering earlier predictions.

### Evaluation Metrics

Calculate:

- Classification accuracy
- Multiclass Brier score
- Multiclass log loss
- Probability calibration
- Performance by season
- Performance by predicted outcome
- Performance against baseline models

### Baselines

Compare the optimized Elo prediction model against:

1. Historical home/draw/away outcome frequencies computed from past training data.
2. A basic Elo model with fixed, untuned parameters.

Use identical evaluation periods for fair comparisons.

### Python Libraries

Use:
- Pandas for evaluation data preparation and grouping.
- NumPy for numerical metrics and probability arrays.
- SciPy for parameter optimization.
- Matplotlib for analytical plots.

Generate calibration plots, performance-over-time graphs, and model comparison charts.

All reported metrics must be computed from actual historical predictions.

Do not fabricate model accuracy or other performance results.

## 9. Automated Match Updates

Integrate football-data.org for ongoing EPL fixtures and finished results.

Use an API key stored in an environment variable.

Implement an automated update job that runs hourly.

The job should:

1. Fetch relevant recently completed fixtures.
2. Normalize the API response.
3. Match clubs to canonical team IDs.
4. Identify matches already in the database.
5. Insert new results or reconcile existing match records.
6. Detect corrected scores and status changes.
7. Update or recompute Elo ratings as needed.
8. Refresh upcoming fixture predictions.
9. Record synchronization status and errors.

### Reliability Requirements

- Respect API rate limits and free-tier restrictions.
- Use retries with exponential backoff for transient failures.
- Handle HTTP 429 responses appropriately.
- Avoid duplicate processing.
- Do not update Elo for unfinished, postponed, cancelled, or abandoned fixtures.
- Ensure failed API calls cannot corrupt stored data.
- Use structured logging for troubleshooting.

Do not assume the free API provides every desired historical or fixture field. Verify provider capabilities and implement graceful fallbacks.

The app must remain usable with previously stored data when the external API is unavailable.

## 10. Frontend Design and User Experience

Create a visually polished, modern football analytics dashboard.

Use React, TypeScript, Tailwind CSS, and Recharts.

The design should feel like a professional football statistics platform rather than a generic admin dashboard.

Prioritize:
- Clean typography
- Consistent spacing
- Strong visual hierarchy
- Responsive layouts
- Intuitive navigation
- Accessible controls
- Smooth but restrained interactions
- Working light and dark modes

### Homepage

Display:
- Current EPL Elo rankings
- Upcoming fixtures and predictions
- Recently completed matches
- Biggest Elo gainers and losers
- Navigation to team profiles and model analytics

### Elo Leaderboard

Display:
- Rank
- Club crest
- Team name
- Current Elo rating
- Rating change over the last five matches
- Recent form

Allow sorting and searching.

Make it clear that Elo rankings are different from the official Premier League points table.

### Team Profile Pages

Each club should have its own page containing:
- Team name and crest
- Current Elo rating
- Elo rank
- Interactive rating history graph
- Recent match results
- Rating gained or lost after each match
- Upcoming fixtures
- Recent form

### Match Prediction Page

Allow users to select two EPL clubs and specify the home team.

Display:
- Both club crests and names
- Current Elo ratings
- Home-win probability
- Draw probability
- Away-win probability
- A probability distribution visualization
- A concise explanation of the prediction

Support predictions for scheduled fixtures as well as hypothetical matchups.

### Model Analytics Dashboard

Display:
- Historical backtest accuracy
- Brier score
- Log loss
- Calibration charts
- Performance by season
- Comparison with baseline models
- Historical prediction results

Use Recharts for interactive visualizations.

Matplotlib should be used for Python-based analytical reports, not as the primary React charting system.

### UX Reliability

Implement:
- Loading skeletons
- Empty states
- Error messages
- Retry options when appropriate
- Responsive mobile layouts
- Proper navigation states

Never show fake data as if it were real.

If data is unavailable, clearly explain that it is unavailable.

## 11. FastAPI Backend

Create clearly organized REST API endpoints for the frontend.

Suggested endpoint groups:

- `/api/teams`
- `/api/teams/{team_id}`
- `/api/teams/{team_id}/history`
- `/api/ratings`
- `/api/matches/recent`
- `/api/fixtures/upcoming`
- `/api/predictions`
- `/api/backtest/summary`
- `/api/backtest/calibration`
- `/api/model/config`

Use Pydantic response schemas and consistent error handling.

Document endpoints using FastAPI's automatically generated OpenAPI documentation.

Keep database operations, business logic, prediction logic, and HTTP route handlers separated.

## 12. Software Architecture

Use a modular, maintainable project structure.

Suggested organization:

```text
premier-league-elo/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── ingestion/
│   │   ├── elo/
│   │   ├── predictions/
│   │   ├── backtesting/
│   │   ├── services/
│   │   └── main.py
│   ├── tests/
│   ├── scripts/
│   ├── alembic/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── services/
│   │   └── types/
│   └── package.json
├── data/
├── docs/
├── .github/
│   └── workflows/
├── .env.example
└── README.md
```

This structure is a starting point. Adjust it if a simpler architecture is more maintainable.

Do not overengineer the application with unnecessary abstractions or microservices.

## 13. Testing and Quality Assurance

Write meaningful automated tests.

### Elo Engine Tests
- Expected-score calculation
- Win, draw, and loss updates
- Goal-difference multipliers
- Home advantage
- Zero-sum rating changes
- Chronological ordering
- Idempotency
- Full recomputation
- Season transitions

### Data Ingestion Tests
- CSV parsing
- Missing values
- Invalid scores
- Team-name normalization
- Duplicate matches
- Conflicting source records
- Re-importing existing data

### Prediction Tests
- Probabilities sum to 1
- Valid probability bounds
- Home advantage effects
- Identical-rating matchups
- Correct handling of draw probabilities

### Backtesting Tests
- No future-data leakage
- Correct chronological evaluation
- Reproducible metrics
- Baseline comparisons

### API and Database Tests
- Correct endpoint responses
- Validation errors
- Database integrity
- Transaction rollback
- API failure handling

Use mocked API responses and local test fixtures so automated tests do not depend on live football-data.org availability.

Use GitHub Actions to run backend tests, frontend linting, and build checks.

## 14. Security and Configuration

- Never hardcode API keys.
- Keep secrets in environment variables.
- Include `.env.example`.
- Do not commit `.env` files.
- Validate external data before persistence.
- Handle external API failures safely.
- Use appropriate CORS settings.
- Avoid exposing internal exception details to frontend users.
- Centralize Elo and prediction-model parameters.
- Document required configuration.

## 15. Documentation and Deployment

Create a professional README explaining:

1. Project overview and key features.
2. Technology stack.
3. System architecture.
4. Local installation.
5. Environment variable setup.
6. Historical data import.
7. Running the Elo engine.
8. Running parameter optimization.
9. Running backtests.
10. Starting the FastAPI backend.
11. Starting the React frontend.
12. Running the automated updater.
13. Running tests.
14. Deployment instructions.
15. Model limitations and assumptions.

Provide a reproducible local development workflow.

Design the application so the frontend and backend can eventually be deployed publicly.

Account for SQLite persistence and scheduled-worker limitations when selecting a hosting platform.

Do not introduce paid infrastructure unless explicitly approved.

## 16. Development Order

Implement the project in the following phases.

### Phase 1 — Database and Historical Data Ingestion
- Create backend project structure.
- Configure SQLite, SQLAlchemy, and Alembic.
- Define database models.
- Implement canonical team identities and aliases.
- Build historical CSV ingestion using Pandas.
- Import and validate multiple EPL seasons.
- Write ingestion tests.

### Phase 2 — Elo Rating Engine
- Implement expected-score calculations.
- Implement rating updates.
- Add home advantage and goal-difference handling.
- Implement chronological match processing.
- Store rating history.
- Add season transition rules.
- Implement idempotency and recomputation.
- Write comprehensive unit tests.

### Phase 3 — Backtesting and Optimization
- Implement chronological walk-forward backtesting.
- Use NumPy to calculate evaluation metrics.
- Use SciPy to optimize Elo parameters.
- Implement baseline models.
- Use Matplotlib for analytical visualizations.
- Verify there is no data leakage.

### Phase 4 — Prediction Model
- Implement a fitted three-outcome probability model.
- Calibrate and evaluate predictions.
- Integrate optimized Elo parameters.
- Expose prediction services through FastAPI.
- Test probability validity and reproducibility.

### Phase 5 — Automated Live Data Updates
- Integrate football-data.org.
- Fetch finished matches and upcoming fixtures.
- Implement the hourly update job.
- Handle corrections, duplicates, rate limits, and failures.
- Connect updates to rating recalculation.

### Phase 6 — Frontend Application
- Build the React application.
- Create the Elo leaderboard.
- Implement team profile pages.
- Add interactive rating history charts.
- Build fixture prediction cards.
- Add recent match results.
- Build the model analytics dashboard.
- Implement responsive design and dark/light modes.
- Connect every page to real backend endpoints.

### Phase 7 — Final Polish and Deployment
- Improve performance.
- Run complete automated tests.
- Fix UI and backend issues.
- Add GitHub Actions.
- Finalize documentation.
- Prepare deployment.
- Verify the deployed application uses real data and actual model calculations.

## 17. Future Features — Do Not Implement Yet

Potential future enhancements include:

### Head-to-Head Match Simulator
Allow users to compare any two supported clubs and generate hypothetical match predictions.

The basic matchup prediction functionality should exist in the initial application, but advanced simulation features can be added later.

### Monte Carlo Season Simulator
Simulate remaining Premier League fixtures thousands of times to estimate:
- League title probabilities
- Top-four finish probabilities
- Relegation probabilities
- Expected final league positions

These are optional future enhancements and must not delay the core application.

## 18. Critical Development Instructions

Follow these rules throughout development:

1. **Do not build the entire application in one attempt.** Work phase by phase.
2. Complete and test each phase before moving to the next.
3. Ask me before making any major architectural or design decision not already specified.
4. Explain important technical decisions in understandable terms.
5. Do not unnecessarily rewrite working code.
6. Do not introduce unrelated features.
7. Prefer maintainable, readable code over clever but confusing implementations.
8. Use actual football data and real mathematical calculations.
9. Never hardcode ratings, match predictions, or backtest performance metrics.
10. Do not silently ignore errors or failed tests.
11. Clearly distinguish implemented functionality from planned functionality.
12. After each phase, summarize the files created or modified, the functionality implemented, and the tests performed.
13. Tell me exactly how to run and verify each completed phase.
14. Do not claim functionality has been tested unless the relevant tests actually ran successfully.
15. If an external service or API is unavailable, explain the limitation and use clearly identified test fixtures only where appropriate.
16. Keep the application focused on the English Premier League.
17. Build with the goal of producing a genuinely strong software engineering internship portfolio project.

## 19. Start Here

**Begin with Phase 1 only: Database and Historical Data Ingestion.**

Before writing code:

1. Briefly explain the proposed database schema.
2. Explain how team identities will be standardized across historical CSVs and the live API.
3. Explain how historical matches will be imported, validated, and deduplicated.
4. Identify any major decisions that require my approval.

Then implement Phase 1, run the relevant tests, and explain how I can verify the results.

**Do not proceed to Phase 2 until I approve.**