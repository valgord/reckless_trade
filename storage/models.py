from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    git_sha: Mapped[str] = mapped_column(String(64))
    strategy: Mapped[str] = mapped_column(String(128))
    config_hash: Mapped[str] = mapped_column(String(64))
    dataset_id: Mapped[str] = mapped_column(String(256))
    objective: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[dict] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="completed")


class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_news_fingerprint"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(128))
    fingerprint: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class LlmAnalysis(Base):
    __tablename__ = "llm_analyses"
    __table_args__ = (UniqueConstraint("article_id", "model", "prompt_hash", name="uq_llm_analysis_replay"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    article_id: Mapped[str] = mapped_column(String(36), index=True)
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_to_strategy_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    direction: Mapped[float] = mapped_column(Float)
    importance: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    event_type: Mapped[str] = mapped_column(String(64))
    assets: Mapped[list] = mapped_column(JSON)
    response: Mapped[dict] = mapped_column(JSON)


class StrategyDecision(Base):
    __tablename__ = "strategy_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    ts_event: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    strategy: Mapped[str] = mapped_column(String(128), index=True)
    instrument: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    rationale: Mapped[str] = mapped_column(Text, default="")
