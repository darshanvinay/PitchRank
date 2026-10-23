from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"
    league: Mapped[str] = mapped_column(String(10), default="epl", server_default="epl", index=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    crest_url: Mapped[str | None] = mapped_column(String(500))


class TeamAlias(Base):
    __tablename__ = "team_aliases"
    __table_args__ = (UniqueConstraint("source", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    source: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(100))


class ImportRun(Base):
    __tablename__ = "import_runs"
    league: Mapped[str] = mapped_column(String(10), default="epl", server_default="epl", index=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(80))
    location: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64))
    season: Mapped[str] = mapped_column(String(9))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("season", "match_date", "home_team_id", "away_team_id"),
        CheckConstraint("home_team_id != away_team_id"),
        CheckConstraint("home_goals IS NULL OR home_goals >= 0"),
        CheckConstraint("away_goals IS NULL OR away_goals >= 0"),
        CheckConstraint("status IN ('finished','scheduled','postponed','cancelled','abandoned')"),
        CheckConstraint(
            "status != 'finished' OR (home_goals IS NOT NULL AND away_goals IS NOT NULL)"
        ),
        Index("ix_matches_chronology", "match_date", "kickoff_at", "id"),
    )
    league: Mapped[str] = mapped_column(String(10), default="epl", server_default="epl", index=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(80))
    stage: Mapped[str] = mapped_column(String(20), default="domestic", server_default="domestic")
    neutral: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    external_id: Mapped[str | None] = mapped_column(String(100))
    season: Mapped[str] = mapped_column(String(9), index=True)
    match_date: Mapped[date] = mapped_column(Date)
    # Provider kickoff times use the selected league’s local timezone, stored as UTC.
    kickoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    home_goals: Mapped[int | None] = mapped_column(Integer)
    away_goals: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="finished")
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class MatchObservation(Base):
    """Immutable source observations preserve corrections and cross-provider provenance."""

    __tablename__ = "match_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    import_run_id: Mapped[int] = mapped_column(ForeignKey("import_runs.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    config_hash: Mapped[str] = mapped_column(String(64), unique=True)
    parameters: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    needs_rebuild: Mapped[bool] = mapped_column(Boolean, default=True)
    input_hash: Mapped[str | None] = mapped_column(String(64))


class RatingHistory(Base):
    __tablename__ = "rating_history"
    __table_args__ = (UniqueConstraint("match_id", "team_id", "model_version_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), index=True)
    rating_before: Mapped[float] = mapped_column(Float)
    rating_after: Mapped[float] = mapped_column(Float)
    rating_change: Mapped[float] = mapped_column(Float)
    sequence: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SquadValue(Base):
    __tablename__ = "squad_values"
    __table_args__ = (
        UniqueConstraint("season", "team_id"),
        CheckConstraint("value_eur > 0"),
    )
    league: Mapped[str] = mapped_column(String(10), default="epl", server_default="epl", index=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    season: Mapped[str] = mapped_column(String(9), index=True)
    value_eur: Mapped[float] = mapped_column(Float)
    as_of: Mapped[date] = mapped_column(Date)
    source_url: Mapped[str] = mapped_column(String(1000))


class SeasonRating(Base):
    """One current calculation per team/season; no model registry in the MVP."""

    __tablename__ = "season_ratings"
    __table_args__ = (UniqueConstraint("season", "team_id"),)
    league: Mapped[str] = mapped_column(String(10), default="epl", server_default="epl", index=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    season: Mapped[str] = mapped_column(String(9), index=True)
    initial_rating: Mapped[float] = mapped_column(Float)
    rating: Mapped[float] = mapped_column(Float)
    input_hash: Mapped[str] = mapped_column(String(64))
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SeasonHistory(Base):
    __tablename__ = "season_history"
    __table_args__ = (UniqueConstraint("match_id", "team_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    rating_before: Mapped[float] = mapped_column(Float)
    rating_after: Mapped[float] = mapped_column(Float)
    rating_change: Mapped[float] = mapped_column(Float)
    sequence: Mapped[int] = mapped_column(Integer)
