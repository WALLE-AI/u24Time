# -*- coding: utf-8 -*-
"""
Tech Normalizer — 技术域数据标准化器
覆盖: oss / cyber / infra / ai_service 子域
来源: GitHub Trending, HN, NVD CVE, worldmonitor infra status, cyber threats
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


class TechNormalizer:
    """统一技术域标准化入口"""

    # ──────────────────────────────────────────────────────────────
    # OSS: GitHub Trending repo
    # ──────────────────────────────────────────────────────────────
    def normalize_github_trending(self, repo: dict, source_id: str = "tech.oss.github_trending") -> Optional[CanonicalItem]:
        """GitHub trending repo dict (from NewsNow or scraper)"""
        try:
            name = repo.get("title", repo.get("name", repo.get("full_name", "")))
            url = repo.get("url", repo.get("link", f"https://github.com/{name}"))
            description = repo.get("description", repo.get("extra", {}).get("description", ""))
            language = repo.get("language", repo.get("extra", {}).get("language", ""))
            
            # Use extra fields enriched by dual-stage script
            extra = repo.get("extra", {})
            stars = int(repo.get("stars", extra.get("stars", 0)) or 0)
            
            # Read stars_today from hover if available as a string
            hover_val = str(extra.get("hover", "")).replace(" ", "").replace(",", "")
            import re
            nums = re.findall(r'\d+', hover_val)
            stars_today = int(nums[0]) if nums else int(repo.get("starsToday", extra.get("forks", 0)) or 0)

            commits_30d = extra.get("commits_30d", 0)
            last_commit_at = extra.get("last_commit_at")

            title = f"⭐ {name}"
            if language:
                title += f" [{language}]"
            if description:
                title += f" — {description[:80]}"

            # Custom Metric combining stars and commits
            # Activity Score = stars_today + commits_30d * 5
            score = stars_today + min(commits_30d, 100) * 5
            
            severity = SeverityLevel.INFO
            if score >= 600:
                severity = SeverityLevel.CRITICAL if score >= 1000 else SeverityLevel.HIGH
            elif score >= 200:
                severity = SeverityLevel.MEDIUM

            return CanonicalItem(
                item_id=_make_id(source_id, name),
                source_id=source_id,
                source_type=SourceType.SOCIAL,
                domain=DomainType.TECH,
                sub_domain=SubDomainType.OSS,
                title=title,
                body=description[:300] if description else "",
                url=url,
                published_at=last_commit_at or _now_ts(),
                crawled_at=_now_ts(),
                severity_level=severity,
                raw_engagement={"stars": stars, "stars_today": stars_today, "commits_30d": commits_30d, "score": score},
                raw_metadata={"language": language, "repo": name},
                categories=["github", "trending", "oss"],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # OSS: Hacker News item
    # ──────────────────────────────────────────────────────────────
    def normalize_hackernews(self, item: dict, source_id: str = "tech.oss.hackernews") -> Optional[CanonicalItem]:
        """HN Firebase API item"""
        try:
            hn_id = str(item.get("id", ""))
            title = item.get("title", "")
            url = item.get("url", f"https://news.ycombinator.com/item?id={hn_id}")
            score = int(item.get("score", 0))
            comments = int(item.get("descendants", 0))
            by = item.get("by", "")
            ts = item.get("time")
            published = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else _now_ts()

            severity = SeverityLevel.HIGH if score >= 500 else (SeverityLevel.MEDIUM if score >= 200 else SeverityLevel.INFO)

            return CanonicalItem(
                item_id=_make_id(source_id, hn_id),
                source_id=source_id,
                source_type=SourceType.NEWS,
                domain=DomainType.TECH,
                sub_domain=SubDomainType.OSS,
                title=title,
                url=url,
                author=by,
                published_at=published,
                crawled_at=_now_ts(),
                severity_level=severity,
                raw_engagement={"score": score, "comments": comments},
                raw_metadata={"hn_id": hn_id},
                categories=["hackernews", "tech", "dev"],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Cyber: NVD CVE
    # ──────────────────────────────────────────────────────────────
    def normalize_nvd_cve(self, cve_item: dict, source_id: str = "tech.cyber.nvd_cve") -> Optional[CanonicalItem]:
        """NVD API 2.0 vulnerability item"""
        try:
            cve = cve_item.get("cve", cve_item)
            cve_id = cve.get("id", cve_item.get("id", ""))
            published = cve.get("published", _now_ts())

            # Description (English preferred)
            descs = cve.get("descriptions", [])
            desc_text = next((d["value"] for d in descs if d.get("lang") == "en"), "")

            # CVSS v3.1 base score → severity
            metrics = cve.get("metrics", {})
            cvss_score = None
            for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
                arr = metrics.get(key, [])
                if arr:
                    cvss_score = arr[0].get("cvssData", {}).get("baseScore")
                    break

            severity_map_cvss = {9.0: SeverityLevel.CRITICAL, 7.0: SeverityLevel.HIGH, 4.0: SeverityLevel.MEDIUM}
            severity = SeverityLevel.INFO
            if cvss_score is not None:
                for threshold, sev in sorted(severity_map_cvss.items(), reverse=True):
                    if cvss_score >= threshold:
                        severity = sev
                        break

            title = f"[CVE] {cve_id}"
            if cvss_score is not None:
                title += f" CVSS:{cvss_score}"
            if desc_text:
                title += f" — {desc_text[:120]}"

            return CanonicalItem(
                item_id=_make_id(source_id, cve_id),
                source_id=source_id,
                source_type=SourceType.CYBER,
                domain=DomainType.TECH,
                sub_domain=SubDomainType.CYBER,
                title=title,
                body=desc_text[:500],
                url=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
                published_at=published,
                crawled_at=_now_ts(),
                severity_level=severity,
                raw_metadata={"cve_id": cve_id, "cvss_score": cvss_score, "metrics": metrics},
                categories=["cve", "vulnerability", "security"],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Infra: Service status entry
    # ──────────────────────────────────────────────────────────────
    def normalize_service_status(self, status: dict, source_id: str = "tech.infra.cloud_aws") -> Optional[CanonicalItem]:
        """worldmonitor ServiceStatus proto-style dict"""
        try:
            service_id = status.get("id", "")
            name = status.get("name", service_id)
            svc_status = status.get("status", "SERVICE_OPERATIONAL_STATUS_UNSPECIFIED")
            description = status.get("description", "")
            url = status.get("url", "")

            is_issue = "OUTAGE" in svc_status or "DEGRADED" in svc_status

            severity_map = {
                "MAJOR_OUTAGE": SeverityLevel.CRITICAL,
                "PARTIAL_OUTAGE": SeverityLevel.HIGH,
                "DEGRADED": SeverityLevel.MEDIUM,
                "MAINTENANCE": SeverityLevel.LOW,
            }
            severity = SeverityLevel.INFO
            for key, sev in severity_map.items():
                if key in svc_status:
                    severity = sev
                    break

            status_emoji = {
                "MAJOR_OUTAGE": "🔴", "PARTIAL_OUTAGE": "🟠",
                "DEGRADED": "🟡", "MAINTENANCE": "🔵", "OPERATIONAL": "🟢",
            }
            emoji = next((v for k, v in status_emoji.items() if k in svc_status), "⚪")

            title = f"{emoji} {name}: {description or svc_status.replace('SERVICE_OPERATIONAL_STATUS_', '')}"
            if is_issue:
                title = f"[服务故障] {title}"

            return CanonicalItem(
                item_id=_make_id(source_id, service_id, svc_status),
                source_id=source_id or f"tech.infra.{service_id}",
                source_type=SourceType.GEO,
                domain=DomainType.TECH,
                sub_domain=SubDomainType.INFRA,
                title=title,
                url=url,
                published_at=_now_ts(),
                crawled_at=_now_ts(),
                severity_level=severity,
                raw_metadata={"service_id": service_id, "status": svc_status},
                categories=["infra", "status", service_id],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Cyber: Feodo Tracker C2 IP row
    # ──────────────────────────────────────────────────────────────
    def normalize_feodo(self, row: dict, source_id: str = "tech.cyber.feodo") -> Optional[CanonicalItem]:
        """Feodo Tracker CSV row dict"""
        try:
            ip_address = row.get("ip_address", row.get("ip", ""))
            port = row.get("dst_port", row.get("port", ""))
            malware = row.get("malware", "")
            status = row.get("status", "")

            title = f"[C2] {malware} @ {ip_address}:{port} ({status})"

            return CanonicalItem(
                item_id=_make_id(source_id, ip_address, str(port)),
                source_id=source_id,
                source_type=SourceType.CYBER,
                domain=DomainType.TECH,
                sub_domain=SubDomainType.CYBER,
                title=title,
                url="https://feodotracker.abuse.ch/",
                published_at=_now_ts(),
                crawled_at=_now_ts(),
                severity_level=SeverityLevel.HIGH,
                raw_metadata={"ip": ip_address, "port": port, "malware": malware, "status": status},
                categories=["c2", "botnet", "threat", malware.lower()],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Cyber: URLhaus malicious URL
    # ──────────────────────────────────────────────────────────────
    def normalize_urlhaus(self, url_item: dict, source_id: str = "tech.cyber.urlhaus") -> Optional[CanonicalItem]:
        """URLhaus URL item dict"""
        try:
            url = url_item.get("url", "")
            url_status = url_item.get("url_status", "")
            threat = url_item.get("threat", "")
            tags = url_item.get("tags", [])
            date_added = url_item.get("date_added", _now_ts())

            title = f"[{threat}] {url[:100]} ({url_status})"

            return CanonicalItem(
                item_id=_make_id(source_id, url),
                source_id=source_id,
                source_type=SourceType.CYBER,
                domain=DomainType.TECH,
                sub_domain=SubDomainType.CYBER,
                title=title,
                url="https://urlhaus.abuse.ch/",
                published_at=date_added,
                crawled_at=_now_ts(),
                severity_level=SeverityLevel.HIGH,
                raw_metadata={"malicious_url": url, "threat": threat, "status": url_status, "tags": tags},
                categories=["urlhaus", "malware", "phishing"] + (tags if isinstance(tags, list) else []),
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # AI Service Status (same schema as infra but different domain-tag)
    # ──────────────────────────────────────────────────────────────
    def normalize_ai_service_status(self, status: dict, source_id: str = "tech.ai.openai_status") -> Optional[CanonicalItem]:
        """AI service status page response"""
        item = self.normalize_service_status(status, source_id)
        if item:
            item.sub_domain = SubDomainType.AI_SERVICE
            item.categories = ["ai", "status", status.get("id", "")]
        return item

    # ──────────────────────────────────────────────────────────────
    # AI Trend: Hugging Face Models/Datasets
    # ──────────────────────────────────────────────────────────────
    def normalize_hf_trend(self, item: dict, source_id: str = "tech.ai.hf_models") -> Optional[CanonicalItem]:
        """HuggingFace API model/dataset item"""
        try:
            name = item.get("id", item.get("modelId", ""))
            author = item.get("author", "")
            likes = item.get("likes", 0)
            downloads = item.get("downloads", 0)
            tags = item.get("tags", [])
            is_dataset = "dataset" in source_id

            title = f"🤗 {name}"
            if downloads:
                title += f" [⬇️ {downloads}]"
            
            body = f"Author: {author} | Likes: {likes}\nTags: {', '.join(tags[:5])}"

            return CanonicalItem(
                item_id=_make_id(source_id, name),
                source_id=source_id,
                source_type=SourceType.SOCIAL,
                domain=DomainType.TECH,
                sub_domain=SubDomainType.OSS,
                title=title,
                body=body,
                url=f"https://huggingface.co/{'datasets/' if is_dataset else ''}{name}",
                published_at=_now_ts(),
                crawled_at=_now_ts(),
                severity_level=SeverityLevel.HIGH if downloads > 1000 else SeverityLevel.INFO,
                raw_engagement={"likes": likes, "downloads": downloads},
                raw_metadata={"tags": tags, "author": author},
                categories=["huggingface", "ai", "dataset" if is_dataset else "model"],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # AI Trend: ModelScope Models/Datasets
    # ──────────────────────────────────────────────────────────────
    def normalize_ms_trend(self, item: dict, source_id: str = "tech.ai.ms_models") -> Optional[CanonicalItem]:
        """ModelScope API model/dataset item"""
        try:
            namespace = item.get("Namespace", "")
            name = item.get("Name", "")
            full_name = f"{namespace}/{name}"
            description = item.get("Description", "")
            views = item.get("ViewCount", 0)
            downloads = item.get("DownloadCount", 0)
            is_dataset = "dataset" in source_id

            title = f"💠 {full_name}"
            if views:
                title += f" [👁️ {views}]"
            
            return CanonicalItem(
                item_id=_make_id(source_id, full_name),
                source_id=source_id,
                source_type=SourceType.SOCIAL,
                domain=DomainType.TECH,
                sub_domain=SubDomainType.OSS,
                title=title,
                body=description[:300],
                url=f"https://modelscope.cn/{'datasets/' if is_dataset else 'models/'}{full_name}/summary",
                published_at=_now_ts(),
                crawled_at=_now_ts(),
                severity_level=SeverityLevel.HIGH if views > 1000 else SeverityLevel.INFO,
                raw_engagement={"views": views, "downloads": downloads},
                raw_metadata={"namespace": namespace, "name": name},
                categories=["modelscope", "ai", "dataset" if is_dataset else "model"],
            )
        except Exception:
            return None


tech_normalizer = TechNormalizer()
