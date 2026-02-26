# -*- coding: utf-8 -*-
"""
Academic Normalizer — 学术域数据标准化器
覆盖: paper / conference / prediction 子域
来源: arXiv, HuggingFace Daily Papers, Semantic Scholar, Polymarket
"""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from typing import Optional

from data_alignment.schema import (
    CanonicalItem, SourceType, SeverityLevel, DomainType, SubDomainType,
)


def _now_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_id(*parts: str) -> str:
    return hashlib.md5(":".join(str(p) for p in parts).encode()).hexdigest()[:16]


class AcademicNormalizer:
    """统一学术域标准化入口"""

    # ──────────────────────────────────────────────────────────────
    # arXiv paper (feedparser entry dict)
    # ──────────────────────────────────────────────────────────────
    def normalize_arxiv_paper(self, entry: dict, category: str = "cs.AI") -> Optional[CanonicalItem]:
        """feedparser arXiv entry → CanonicalItem"""
        try:
            arxiv_id = entry.get("id", "")
            title = entry.get("title", "").replace("\n", " ").strip()
            summary = (entry.get("summary") or "").replace("\n", " ").strip()[:500]
            link = entry.get("link", arxiv_id)
            published = entry.get("published", _now_ts())
            authors_raw = entry.get("authors", [])
            if authors_raw and isinstance(authors_raw[0], dict):
                authors = [a.get("name", "") for a in authors_raw[:5]]
            else:
                authors = authors_raw[:5]

            # LLM/AI topics get MEDIUM severity (高关注)
            hot_terms = {"llm", "gpt", "transformer", "diffusion", "agent", "reasoning", "arxiv"}
            title_lower = title.lower()
            severity = SeverityLevel.MEDIUM if any(t in title_lower for t in hot_terms) else SeverityLevel.INFO

            return CanonicalItem(
                item_id=_make_id("arxiv", arxiv_id, category),
                source_id=f"academic.arxiv.{category.lower().replace('.', '_')}",
                source_type=SourceType.NEWS,
                domain=DomainType.ACADEMIC,
                sub_domain=SubDomainType.PAPER,
                title=title,
                body=summary,
                url=link,
                author=", ".join(authors),
                published_at=published,
                crawled_at=_now_ts(),
                severity_level=severity,
                raw_metadata={"arxiv_id": arxiv_id, "category": category, "authors": authors},
                categories=["arxiv", "paper", category.lower()],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # HuggingFace Daily Papers — 🎓 Academic (not Technology)
    # ──────────────────────────────────────────────────────────────
    def normalize_huggingface_paper(self, paper: dict) -> Optional[CanonicalItem]:
        """HuggingFace /api/daily_papers item"""
        try:
            paper_id = paper.get("id", "")
            title = paper.get("paper", {}).get("title", paper.get("title", ""))
            summary = (paper.get("paper", {}).get("summary") or paper.get("summary", ""))[:500]
            published = paper.get("publishedAt", paper.get("paper", {}).get("publishedAt", _now_ts()))
            upvotes = paper.get("numComments", paper.get("upvotes", 0))

            # HF papers always AI-related → MEDIUM
            return CanonicalItem(
                item_id=_make_id("hf_paper", paper_id, title[:20]),
                source_id="academic.huggingface.papers",
                source_type=SourceType.NEWS,
                domain=DomainType.ACADEMIC,
                sub_domain=SubDomainType.PAPER,
                title=title,
                body=summary,
                url=f"https://huggingface.co/papers/{paper_id}",
                published_at=published,
                crawled_at=_now_ts(),
                severity_level=SeverityLevel.MEDIUM,
                raw_engagement={"comments": upvotes},
                raw_metadata={"hf_id": paper_id},
                categories=["huggingface", "ai", "paper"],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Semantic Scholar
    # ──────────────────────────────────────────────────────────────
    def normalize_semantic_scholar(self, paper: dict) -> Optional[CanonicalItem]:
        """Semantic Scholar /graph/v1/paper response"""
        try:
            paper_id = paper.get("paperId", "")
            title = paper.get("title", "")
            abstract = (paper.get("abstract") or "")[:500]
            citation_count = paper.get("citationCount", 0)
            published = paper.get("year", "")
            authors = [a.get("name", "") for a in paper.get("authors", [])[:5]]
            url = paper.get("url", f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}")

            severity = SeverityLevel.HIGH if citation_count >= 1000 else (SeverityLevel.MEDIUM if citation_count >= 100 else SeverityLevel.INFO)

            return CanonicalItem(
                item_id=_make_id("s2", paper_id),
                source_id="academic.semantic_scholar.trending",
                source_type=SourceType.NEWS,
                domain=DomainType.ACADEMIC,
                sub_domain=SubDomainType.PAPER,
                title=title,
                body=abstract,
                url=url,
                author=", ".join(authors),
                published_at=str(published),
                crawled_at=_now_ts(),
                severity_level=severity,
                raw_engagement={"citations": citation_count},
                raw_metadata={"s2_id": paper_id, "citation_count": citation_count},
                categories=["semantic-scholar", "paper", "citation"],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Tech Events / Conferences
    # ──────────────────────────────────────────────────────────────
    def normalize_tech_event(self, event: dict, source_id: str = "academic.conf.tech_events") -> Optional[CanonicalItem]:
        """Technology conference or academic event"""
        try:
            name = event.get("name", event.get("title", ""))
            url = event.get("url", event.get("link", ""))
            date = str(event.get("startDate", event.get("date", "")))
            location = event.get("location", "")
            tags = event.get("tags", [])

            title = f"[会议] {name}"
            if date:
                title += f" — {date}"
            if location:
                title += f" @ {location}"

            return CanonicalItem(
                item_id=_make_id(source_id, name, date),
                source_id=source_id,
                source_type=SourceType.NEWS,
                domain=DomainType.ACADEMIC,
                sub_domain=SubDomainType.CONF,
                title=title,
                url=url,
                published_at=_now_ts(),
                crawled_at=_now_ts(),
                severity_level=SeverityLevel.INFO,
                raw_metadata={"event": event},
                categories=["conference", "event"] + (tags if isinstance(tags, list) else []),
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Polymarket prediction market
    # ──────────────────────────────────────────────────────────────
    def normalize_prediction_market(self, market: dict, source_id: str = "academic.prediction.polymarket") -> Optional[CanonicalItem]:
        """Polymarket Gamma API market item"""
        try:
            market_id = market.get("id", "")
            title = market.get("title", market.get("question", ""))
            yes_price = market.get("yesPrice", 0.5)
            volume = market.get("volume", 0)
            url = market.get("url", f"https://polymarket.com/market/{market.get('slug', market_id)}")

            # High confidence (>80% or <20%) → MEDIUM severity
            severity = SeverityLevel.MEDIUM if (yes_price >= 0.8 or yes_price <= 0.2) else SeverityLevel.INFO

            return CanonicalItem(
                item_id=_make_id(source_id, market_id),
                source_id=source_id,
                source_type=SourceType.MARKET,
                domain=DomainType.ACADEMIC,
                sub_domain=SubDomainType.PREDICTION,
                title=f"[预测市场] {title} — YES {yes_price:.0%}",
                url=url,
                published_at=_now_ts(),
                crawled_at=_now_ts(),
                severity_level=severity,
                raw_engagement={"volume": int(volume)},
                raw_metadata={"market_id": market_id, "yes_price": yes_price, "volume": volume},
                categories=["prediction", "polymarket", "market"],
            )
        except Exception:
            return None

    def normalize_polymarket(self, market: dict, source_id: str = "academic.prediction.polymarket") -> Optional[CanonicalItem]:
        """Alias for normalize_prediction_market (pipeline compatibility)"""
        return self.normalize_prediction_market(market, source_id)


academic_normalizer = AcademicNormalizer()
