# -*- coding: utf-8 -*-
import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import settings

_RETRY = dict(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError)),
)

HEADERS = {"User-Agent": "U24Time-Crawler/1.0 (https://github.com/u24time)"}

class GithubAdapter:
    """
    GitHub API Adapter.
    用于增补/增强现有的 GitHub 热榜数据（获取项目真实活跃度）。
    """
    def __init__(self):
        self.token = settings.GITHUB_TOKEN

    @property
    def _headers(self) -> dict:
        h = dict(HEADERS)
        if self.token:
            h["Authorization"] = f"token {self.token}"
        return h

    @retry(**_RETRY)
    async def fetch_repo_activity(self, owner_repo: str) -> dict:
        """Fetch repo details and 30-day commit count."""
        url = f"https://api.github.com/repos/{owner_repo}"
        stats = {
            "commits_30d": 0,
            "last_commit_at": None,
            "stars": 0,
            "forks": 0
        }
        async with httpx.AsyncClient(timeout=10, headers=self._headers, follow_redirects=True) as client:
            try:
                # 1. 仓库基本信息
                resp = await client.get(url)
                if resp.status_code == 404:
                    return stats
                resp.raise_for_status()
                repo_data = resp.json()
                stats["stars"] = repo_data.get("stargazers_count", 0)
                stats["forks"] = repo_data.get("forks_count", 0)
                stats["last_commit_at"] = repo_data.get("pushed_at") or repo_data.get("updated_at")

                # 2. 统计近 30 天的 Commit 数
                since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
                commits_url = f"https://api.github.com/repos/{owner_repo}/commits"
                params = {"since": since, "per_page": 1}
                
                resp_commits = await client.get(commits_url, params=params)
                if resp_commits.status_code == 200:
                    links = resp_commits.headers.get("Link", "")
                    if links and 'rel="last"' in links:
                        match = re.search(r'page=(\d+)>; rel="last"', links)
                        if match:
                            stats["commits_30d"] = int(match.group(1))
                    else:
                        stats["commits_30d"] = len(resp_commits.json())
            except httpx.HTTPStatusError as e:
                # 如果是 403 限速或鉴权失败，不打断全部
                logger.warning(f"GithubAdapter: API 报错或限流 {owner_repo} -> {e}")
            except Exception as e:
                logger.warning(f"GithubAdapter: 拉取失败 {owner_repo} -> {e}")
                
        return stats

    async def enrichen_trending_repos(self, repos: list[dict]) -> list[dict]:
        """并发获取多维指标信息"""
        semaphore = asyncio.Semaphore(10)

        async def _enrich(repo_dict: dict):
            # 从 url 中提取 owner/repo
            url = repo_dict.get("url", repo_dict.get("link", ""))
            name = repo_dict.get("title", repo_dict.get("name", ""))
            owner_repo = None
            
            if "github.com/" in url:
                parts = url.split("github.com/")[-1].split("/")
                if len(parts) >= 2:
                    owner_repo = f"{parts[0]}/{parts[1]}"
            elif "/" in name:
                owner_repo = name.replace(" ", "")

            if owner_repo:
                async with semaphore:
                    stats = await self.fetch_repo_activity(owner_repo)
                    if "extra" not in repo_dict or not isinstance(repo_dict["extra"], dict):
                        repo_dict["extra"] = {}
                    repo_dict["extra"]["commits_30d"] = stats["commits_30d"]
                    repo_dict["extra"]["last_commit_at"] = stats["last_commit_at"]
                    # 优先使用实时拉取的真实 star
                    if stats["stars"] > 0:
                        repo_dict["stars"] = stats["stars"]
                        repo_dict["extra"]["stars"] = stats["stars"]
            return repo_dict

        tasks = [_enrich(r) for r in repos]
        enriched = await asyncio.gather(*tasks, return_exceptions=True)
        results = []
        for r, orig in zip(enriched, repos):
            if isinstance(r, Exception):
                logger.warning(f"GithubAdapter worker failed: {r}")
                results.append(orig)
            else:
                results.append(r)
        return results
