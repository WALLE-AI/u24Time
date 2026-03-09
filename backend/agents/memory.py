# -*- coding: utf-8 -*-
"""
MemoryIndexManager — 长期记忆管理器
深度参考 OpenClaw src/memory/ 全模块实现

核心特性:
  - 三表存储架构: files / chunks / chunks_vec (向量) / chunks_fts (FTS5 BM25)
  - 多 Provider 嵌入 Fallback: OpenAI → Gemini → Ollama → FTS-only 降级
  - 五步混合检索流水线:
      1. 多语言关键词扩展 (ZH/JA/KO/EN/AR 停用词)
      2. 并行 BM25 关键词搜索 + 向量表 KNN 搜索
      3. 加权分数合并 (vectorWeight * vecScore + textWeight * textScore)
      4. 时序衰减 (指数半衰期, halfLifeDays=30)
      5. MMR 多样性重排序 (lambda=0.7, Jaccard 相似度)
  - SQLite READONLY 自动恢复
  - 嵌入缓存 (embedding_cache 表)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from loguru import logger

# ─── 常量 ────────────────────────────────────────────────────────────────────
VECTOR_TABLE   = "chunks_vec"
FTS_TABLE      = "chunks_fts"
CACHE_TABLE    = "embedding_cache"
SNIPPET_MAX    = 700
CHUNK_SIZE     = 500
CHUNK_OVERLAP  = 50
DEFAULT_K      = 5
CANDIDATE_MULT = 4          # candidates = k × CANDIDATE_MULT
DEFAULT_VECTOR_WEIGHT = 0.7
DEFAULT_TEXT_WEIGHT   = 0.3
DEFAULT_HALF_LIFE_DAYS = 30.0
DEFAULT_MMR_LAMBDA    = 0.7
BATCH_FAILURE_LIMIT   = 2

# ─── 多语言停用词 ─────────────────────────────────────────────────────────────
_STOP_WORDS_EN = {
    "a","an","the","this","that","these","those","i","me","my","we","our",
    "you","your","he","she","it","they","them","is","are","was","were",
    "be","been","being","have","has","had","do","does","did","will","would",
    "could","should","can","may","might","in","on","at","to","for","of",
    "with","by","from","about","into","through","during","before","after",
    "above","below","between","under","over","and","or","but","if","then",
    "because","as","while","when","where","what","which","who","how","why",
    "yesterday","today","tomorrow","earlier","later","recently","now","just",
    "thing","things","stuff","something","anything","everything","nothing",
    "please","help","find","show","get","tell","give",
}
_STOP_WORDS_ZH = {
    "我","我们","你","你们","他","她","它","他们","这","那","这个","那个",
    "这些","那些","的","了","着","过","得","地","吗","呢","吧","啊","呀",
    "嘛","啦","是","有","在","被","把","给","让","用","到","去","来","做",
    "说","看","找","想","要","能","会","可以","和","与","或","但","但是",
    "因为","所以","如果","虽然","而","也","都","就","还","又","再","才",
    "只","之前","以前","之后","以后","刚才","现在","昨天","今天","明天",
    "最近","东西","事情","事","什么","哪个","哪些","怎么","为什么","多少",
    "请","帮","帮忙","告诉",
}
_STOP_WORDS_JA = {
    "これ","それ","あれ","この","その","あの","ここ","そこ","あそこ",
    "する","した","して","です","ます","いる","ある","なる","できる",
    "の","こと","もの","ため","そして","しかし","また","でも","から",
    "まで","より","だけ","なぜ","どう","何","いつ","どこ","誰","どれ",
    "昨日","今日","明日","最近","今","さっき","前","後",
}
_STOP_WORDS_KO = {
    "은","는","이","가","을","를","의","에","에서","로","으로","와","과",
    "도","만","까지","부터","한테","에게","께","처럼","같이","보다","마다",
    "밖에","대로","나","나는","내가","나를","너","우리","저","저희","그",
    "그녀","그들","이것","저것","그것","여기","저기","거기","있다","없다",
    "하다","되다","이다","아니다","주다","오다","가다","것","거","등","수",
    "때","곳","중","분","잘","더","또","매우","정말","아주","많이","너무",
    "좀","그리고","하지만","그래서","그런데","그러나","또는","그러면",
    "왜","어떻게","뭐","언제","어디","누구","무엇","어떤","어제","오늘",
    "내일","최근","지금","아까","나중","전에","제발","부탁",
}
_STOP_WORDS_AR = {
    "ال","و","أو","لكن","ثم","بل","أنا","نحن","هو","هي","هم","هذا",
    "هذه","ذلك","تلك","هنا","هناك","من","إلى","في","على","عن","مع",
    "بين","كان","كانت","يكون","تكون","صار","أصبح","يمكن","ممكن",
    "بالأمس","اليوم","غدا","الآن","قبل","بعد","مؤخرا","لماذا","كيف",
    "ماذا","متى","أين","هل","ساعد",
}

_ALL_STOP_WORDS = (
    _STOP_WORDS_EN | _STOP_WORDS_ZH | _STOP_WORDS_JA
    | _STOP_WORDS_KO | _STOP_WORDS_AR
)

_KO_PARTICLES = sorted([
    "에서","으로","에게","한테","처럼","같이","보다","까지","부터",
    "마다","밖에","대로","은","는","이","가","을","를","의","에",
    "로","와","과","도","만"
], key=len, reverse=True)


# ─── 관键词扩展 (参考 OpenClaw query-expansion.ts) ──────────────────────────

def _tokenize(text: str) -> list[str]:
    """多语言分词 — CJK n-gram + 英文空白分割"""
    tokens: list[str] = []
    normalized = text.lower().strip()

    segments = re.split(r'[\s\p{P}]+' if False else r'[\s.,;:!?"\'\(\)\[\]{}<>@#$%^&*+=|~`]+', normalized)
    for seg in segments:
        if not seg:
            continue
        # 日文 (kana 字符)
        if re.search(r'[\u3040-\u30ff]', seg):
            parts = re.findall(
                r'[a-z0-9_]+|[\u30a0-\u30ff\u30fc]+|[\u4e00-\u9fff]+|[\u3040-\u309f]{2,}', seg
            )
            for part in parts:
                if re.match(r'^[\u4e00-\u9fff]+$', part):
                    tokens.append(part)
                    for i in range(len(part) - 1):
                        tokens.append(part[i] + part[i + 1])
                else:
                    tokens.append(part)
        # 中文
        elif re.search(r'[\u4e00-\u9fff]', seg):
            chars = [c for c in seg if '\u4e00' <= c <= '\u9fff']
            tokens.extend(chars)
            for i in range(len(chars) - 1):
                tokens.append(chars[i] + chars[i + 1])
        # 韩文 (Hangul)
        elif re.search(r'[\uac00-\ud7af\u3131-\u3163]', seg):
            stem = None
            for particle in _KO_PARTICLES:
                if len(seg) > len(particle) and seg.endswith(particle):
                    stem = seg[: -len(particle)]
                    break
            stem_ok = stem and len(stem) >= 2 and stem not in _STOP_WORDS_KO
            if seg not in _STOP_WORDS_KO and (not stem or stem not in _STOP_WORDS_KO):
                tokens.append(seg)
            if stem_ok:
                tokens.append(stem)
        else:
            tokens.append(seg)

    return tokens


def extract_keywords(query: str) -> list[str]:
    """多语言停用词过滤 → 有效关键词列表"""
    seen: set[str] = set()
    result: list[str] = []
    for token in _tokenize(query):
        if token in _ALL_STOP_WORDS:
            continue
        if len(token) < 2 and re.match(r'^[a-zA-Z]$', token):
            continue
        if re.match(r'^\d+$', token):
            continue
        if token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


# ─── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class MemorySearchResult:
    chunk_id: str
    path: str           # 来源路径 / 标识
    snippet: str        # 文本摘要
    score: float
    source: str = "long_term"
    start_line: int = 0
    end_line: int = 0
    metadata: dict = field(default_factory=dict)


# ─── 混合检索算法 ─────────────────────────────────────────────────────────────

def _bm25_rank_to_score(rank: float) -> float:
    """BM25 rank → [0,1] 归一化 (参考 OpenClaw hybrid.ts bm25RankToScore)"""
    if not math.isfinite(rank):
        return 1 / (1 + 999)
    if rank < 0:
        relevance = -rank
        return relevance / (1 + relevance)
    return 1 / (1 + rank)


def _build_fts_query(raw: str) -> Optional[str]:
    """构建 FTS5 查询字符串: tokens → `"t1" AND "t2"`"""
    tokens = re.findall(r'[\w\u4e00-\u9fff\uac00-\ud7af\u3040-\u30ff]+', raw)
    if not tokens:
        return None
    quoted = [f'"{t.replace(chr(34), "")}"' for t in tokens]
    return " AND ".join(quoted)


def _merge_hybrid_results(
    vector_results: list[dict],
    keyword_results: list[dict],
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    text_weight: float = DEFAULT_TEXT_WEIGHT,
) -> list[dict]:
    """加权合并向量 + 关键词搜索结果 (参考 OpenClaw hybrid.ts mergeHybridResults)"""
    by_id: dict[str, dict] = {}

    for r in vector_results:
        by_id[r["chunk_id"]] = {
            **r, "vector_score": r.get("score", 0.0), "text_score": 0.0
        }

    for r in keyword_results:
        cid = r["chunk_id"]
        if cid in by_id:
            by_id[cid]["text_score"] = r.get("text_score", 0.0)
        else:
            by_id[cid] = {
                **r, "vector_score": 0.0, "text_score": r.get("text_score", 0.0)
            }

    merged = []
    for entry in by_id.values():
        score = vector_weight * entry["vector_score"] + text_weight * entry["text_score"]
        merged.append({**entry, "score": score})

    return sorted(merged, key=lambda x: x["score"], reverse=True)


def _apply_temporal_decay(
    results: list[dict],
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    now_ts: Optional[float] = None,
) -> list[dict]:
    """
    时序衰减: score × e^(-λt)  λ = ln2 / halfLifeDays
    常青文件豁免: metadata.evergreen=True 的条目不参与衰减
    """
    if half_life_days <= 0:
        return results
    now = now_ts or time.time()
    lam = math.log(2) / half_life_days
    decayed = []
    for r in results:
        ts = r.get("metadata", {}).get("stored_at")
        evergreen = r.get("metadata", {}).get("evergreen", False)
        if ts and not evergreen:
            age_days = max(0.0, (now - float(ts)) / 86400.0)
            r = {**r, "score": r["score"] * math.exp(-lam * age_days)}
        decayed.append(r)
    return decayed


def _tokenize_for_jaccard(text: str) -> set[str]:
    """MMR Jaccard 分词: 提取小写字母数字词"""
    return set(re.findall(r'[a-z0-9\u4e00-\u9fff\uac00-\ud7af]+', text.lower()))


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _apply_mmr(
    results: list[dict],
    lambda_: float = DEFAULT_MMR_LAMBDA,
    k: int = DEFAULT_K,
) -> list[dict]:
    """
    MMR 多样性重排序 (参考 OpenClaw mmr.ts mmrRerank)
    MMR_score = λ × relevance - (1-λ) × max_Jaccard(candidate, selected)
    """
    if len(results) <= 1:
        return results[:k]

    lambda_ = max(0.0, min(1.0, lambda_))
    if lambda_ == 1.0:
        return results[:k]

    # 分数归一化
    scores = [r["score"] for r in results]
    max_s, min_s = max(scores), min(scores)
    score_range = max_s - min_s or 1.0

    # 预计算 token 集合
    token_cache: dict[str, set[str]] = {}
    for r in results:
        cid = r["chunk_id"]
        token_cache[cid] = _tokenize_for_jaccard(r.get("snippet", ""))

    selected: list[dict] = []
    remaining = list(results)

    while remaining and len(selected) < k:
        best = None
        best_mmr = -float("inf")
        for candidate in remaining:
            norm_rel = (candidate["score"] - min_s) / score_range
            max_sim = max(
                (_jaccard_similarity(token_cache[candidate["chunk_id"]],
                                     token_cache[s["chunk_id"]]) for s in selected),
                default=0.0,
            )
            mmr = lambda_ * norm_rel - (1 - lambda_) * max_sim
            if mmr > best_mmr or (mmr == best_mmr and (best is None or candidate["score"] > best["score"])):
                best_mmr = mmr
                best = candidate
        if best:
            selected.append(best)
            remaining.remove(best)

    return selected


# ─── SQLite 数据库操作 ────────────────────────────────────────────────────────

def _get_db_path(data_dir: str = "data") -> str:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    return os.path.join(data_dir, "memory_index.db")


def _open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-32000")  # 32 MB
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """创建三表架构 (若不存在)"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            path        TEXT NOT NULL UNIQUE,
            source      TEXT NOT NULL DEFAULT 'long_term',
            content_hash TEXT,
            stored_at   REAL NOT NULL,
            metadata    TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id    TEXT NOT NULL UNIQUE,
            file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            content     TEXT NOT NULL,
            start_char  INTEGER DEFAULT 0,
            end_char    INTEGER DEFAULT 0,
            embedding   BLOB,
            provider    TEXT,
            stored_at   REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS embedding_cache (
            text_hash   TEXT PRIMARY KEY,
            embedding   BLOB NOT NULL,
            provider    TEXT NOT NULL,
            cached_at   REAL NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
            USING fts5(chunk_id UNINDEXED, content, prefix='2 3');

        CREATE INDEX IF NOT EXISTS ix_chunks_file_id ON chunks(file_id);
        CREATE INDEX IF NOT EXISTS ix_files_source ON files(source);
    """)
    conn.commit()


# ─── 嵌入 Provider ────────────────────────────────────────────────────────────

class EmbeddingProvider:
    """嵌入向量 Provider 基类"""

    def __init__(self, name: str):
        self.name = name

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    @property
    def dims(self) -> int:
        return 1536


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI text-embedding-3-small"""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        super().__init__("openai")
        self._api_key = api_key
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=self._api_key)
            resp = await client.embeddings.create(model=self._model, input=texts)
            return [item.embedding for item in resp.data]
        except Exception as e:
            raise RuntimeError(f"OpenAI embed failed: {e}") from e

    @property
    def dims(self) -> int:
        return 1536


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama 本地嵌入 (nomic-embed-text, 768 dims)"""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "nomic-embed-text"):
        super().__init__("ollama")
        self._base_url = base_url
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            import httpx
            results = []
            async with httpx.AsyncClient(timeout=30.0) as client:
                for text in texts:
                    resp = await client.post(
                        f"{self._base_url}/api/embeddings",
                        json={"model": self._model, "prompt": text},
                    )
                    resp.raise_for_status()
                    results.append(resp.json()["embedding"])
            return results
        except Exception as e:
            raise RuntimeError(f"Ollama embed failed: {e}") from e

    @property
    def dims(self) -> int:
        return 768


class SiliconFlowEmbeddingProvider(EmbeddingProvider):
    """SiliconFlow 嵌入向量生成 (例如 BAAI/bge-large-zh-v1.5)"""

    def __init__(self, api_key: str, model: str = "BAAI/bge-large-zh-v1.5", dims: int = 1024):
        super().__init__("siliconflow")
        self._api_key = api_key
        self._model = model
        self._dims = dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            import httpx
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json"
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.siliconflow.cn/v1/embeddings",
                    json={"model": self._model, "input": texts},
                    headers=headers
                )
                resp.raise_for_status()
                data = resp.json()["data"]
                # 根据 index 排序确保多文本批次顺序正确
                data = sorted(data, key=lambda x: x.get("index", 0))
                return [item["embedding"] for item in data]
        except Exception as e:
            raise RuntimeError(f"SiliconFlow embed failed: {e}") from e

    @property
    def dims(self) -> int:
        return self._dims


async def _create_embedding_provider() -> Optional[EmbeddingProvider]:
    """
    嵌入 Provider 创建链: SiliconFlow → OpenAI → Ollama → FTS-only (返回 None)
    """
    import os
    
    # 尝试 SiliconFlow
    sf_key = os.environ.get("SILICONFLOW_API_KEY", "")
    if sf_key:
        try:
            model = os.environ.get("SILICONFLOW_EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
            p = SiliconFlowEmbeddingProvider(sf_key, model=model)
            await p.embed(["ping"])
            logger.info(f"MemoryIndexManager: 使用 SiliconFlow 嵌入 Provider (model={model})")
            return p
        except Exception as e:
            logger.warning(f"MemoryIndexManager: SiliconFlow 嵌入不可用 — {e}, 尝试 OpenAI")

    # 尝试 OpenAI
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key and openai_key.startswith("sk-"):
        try:
            p = OpenAIEmbeddingProvider(openai_key)
            await p.embed(["ping"])
            logger.info("MemoryIndexManager: 使用 OpenAI 嵌入 Provider")
            return p
        except Exception as e:
            logger.warning(f"MemoryIndexManager: OpenAI 嵌入不可用 — {e}, 尝试 Ollama")

    # 尝试 Ollama
    try:
        p = OllamaEmbeddingProvider()
        await p.embed(["ping"])
        logger.info("MemoryIndexManager: 使用 Ollama 嵌入 Provider")
        return p
    except Exception as e:
        logger.warning(f"MemoryIndexManager: Ollama 嵌入也不可用 — {e}, 降级为 FTS-only")

    return None


# ─── 主类 ──────────────────────────────────────────────────────────────────────

class MemoryIndexManager:
    """
    长期记忆管理器 — 五步混合检索流水线
    参考 OpenClaw MemoryIndexManager 实现
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        provider: Optional[EmbeddingProvider] = None,
        vector_weight: float = DEFAULT_VECTOR_WEIGHT,
        text_weight: float = DEFAULT_TEXT_WEIGHT,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
        mmr_lambda: float = DEFAULT_MMR_LAMBDA,
        evergreen_paths: Optional[set[str]] = None,
    ):
        self._db_path = db_path or _get_db_path()
        self._provider = provider
        self._vector_weight = vector_weight
        self._text_weight = text_weight
        self._half_life_days = half_life_days
        self._mmr_lambda = mmr_lambda
        self._evergreen_paths: set[str] = evergreen_paths or {"MEMORY", "evergreen"}
        self._readonly_recovery_count = 0
        self._batch_failure_count = 0
        self._lock = asyncio.Lock()

        self._db = _open_db(self._db_path)
        _ensure_schema(self._db)

    @classmethod
    async def create(
        cls,
        db_path: Optional[str] = None,
        **kwargs,
    ) -> "MemoryIndexManager":
        """异步工厂方法 — 自动初始化 Provider"""
        provider = kwargs.pop("provider", None)
        if provider is None:
            provider = await _create_embedding_provider()
        return cls(db_path=db_path, provider=provider, **kwargs)

    # ── 存储 ──────────────────────────────────────────────────────────────────

    async def store_analysis(
        self,
        topic: str,
        content: str,
        metadata: Optional[dict] = None,
        source: str = "long_term",
        evergreen: bool = False,
    ) -> int:
        """
        存储分析报告到记忆索引
        Returns: 存储的 chunk 数量
        """
        meta = metadata or {}
        meta.setdefault("stored_at", time.time())
        meta["evergreen"] = evergreen

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        path = f"{source}/{topic}/{content_hash}"
        stored_at = meta["stored_at"]

        async with self._lock:
            try:
                return await self._store_content(
                    path=path, content=content, source=source,
                    stored_at=stored_at, metadata=meta, content_hash=content_hash
                )
            except sqlite3.OperationalError as e:
                if "readonly" in str(e).lower():
                    logger.warning(f"MemoryIndexManager: SQLite 只读错误, 尝试重连 — {e}")
                    await self._recover_readonly()
                    return await self._store_content(
                        path=path, content=content, source=source,
                        stored_at=stored_at, metadata=meta, content_hash=content_hash
                    )
                raise

    async def _store_content(
        self, path: str, content: str, source: str,
        stored_at: float, metadata: dict, content_hash: str
    ) -> int:
        """实际存储逻辑"""
        # 写入 files 表
        cursor = self._db.execute(
            """
            INSERT INTO files (path, source, content_hash, stored_at, metadata)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                content_hash=excluded.content_hash,
                stored_at=excluded.stored_at,
                metadata=excluded.metadata
            """,
            (path, source, content_hash, stored_at, json.dumps(metadata)),
        )
        self._db.commit()

        file_id = self._db.execute(
            "SELECT id FROM files WHERE path=?", (path,)
        ).fetchone()[0]

        # 分块
        chunks = _chunk_text(content, CHUNK_SIZE, CHUNK_OVERLAP)

        # 批量嵌入
        embeddings: list[Optional[list[float]]] = [None] * len(chunks)
        if self._provider and chunks:
            try:
                embeddings = await self._embed_with_cache(chunks)
            except Exception as e:
                logger.warning(f"MemoryIndexManager: 嵌入失败, 仅用 FTS — {e}")
                self._batch_failure_count += 1

        # 删除旧 chunks (若有)
        self._db.execute(
            "DELETE FROM chunks WHERE file_id=?", (file_id,)
        )
        self._db.execute(
            "DELETE FROM chunks_fts WHERE chunk_id IN "
            "(SELECT chunk_id FROM chunks WHERE file_id=?)", (file_id,)
        )

        count = 0
        for i, (chunk_text, emb) in enumerate(zip(chunks, embeddings)):
            chunk_id = f"{content_hash}:{i}"
            emb_blob = _serialize_vector(emb) if emb else None
            start_char = i * (CHUNK_SIZE - CHUNK_OVERLAP)
            end_char = start_char + len(chunk_text)

            self._db.execute(
                """
                INSERT OR REPLACE INTO chunks
                (chunk_id, file_id, content, start_char, end_char, embedding, provider, stored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (chunk_id, file_id, chunk_text, start_char, end_char,
                 emb_blob, self._provider.name if self._provider else None, stored_at),
            )
            self._db.execute(
                "INSERT OR REPLACE INTO chunks_fts(chunk_id, content) VALUES (?, ?)",
                (chunk_id, chunk_text),
            )
            count += 1

        self._db.commit()
        logger.info(f"MemoryIndexManager: 存储 '{path}' — {count} chunks")
        return count

    # ── 五步混合检索 ──────────────────────────────────────────────────────────

    async def search_history(
        self,
        query: str,
        k: int = DEFAULT_K,
        min_score: float = 0.0,
        enable_temporal_decay: bool = True,
        enable_mmr: bool = True,
        now_ts: Optional[float] = None,
    ) -> list[MemorySearchResult]:
        """
        五步混合检索流水线:
          Step 1: 多语言关键词扩展
          Step 2: BM25 关键词搜索 || 向量 KNN 搜索
          Step 3: 加权合并
          Step 4: 时序衰减 (halfLifeDays=30)
          Step 5: MMR 重排序 (λ=0.7)
        """
        query = query.strip()
        if not query:
            return []

        candidates = max(1, k * CANDIDATE_MULT)

        # Step 1: 多语言关键词扩展
        keywords = extract_keywords(query)

        # Step 2A: FTS-only 降级路径
        if self._provider is None:
            return await self._search_fts_only(keywords or [query], k, min_score)

        # Step 2B: 并行 BM25 + 向量检索
        keyword_results, vector_results = await asyncio.gather(
            self._search_keyword(query, candidates),
            self._search_vector(query, candidates),
            return_exceptions=True,
        )
        if isinstance(keyword_results, Exception):
            logger.warning(f"MemoryIndexManager: BM25 搜索失败 — {keyword_results}")
            keyword_results = []
        if isinstance(vector_results, Exception):
            logger.warning(f"MemoryIndexManager: 向量搜索失败 — {vector_results}")
            vector_results = []

        # Step 3: 加权分数合并
        merged = _merge_hybrid_results(
            vector_results, keyword_results,
            self._vector_weight, self._text_weight
        )

        # Step 4: 时序衰减
        if enable_temporal_decay and self._half_life_days > 0:
            merged = _apply_temporal_decay(merged, self._half_life_days, now_ts)
            merged.sort(key=lambda x: x["score"], reverse=True)

        # 应用 min_score 过滤
        filtered = [r for r in merged if r["score"] >= min_score]
        if not filtered and keyword_results:
            # 放宽: 纯关键词匹配分数 = text_weight, 若高于 min_score 则保留
            relaxed_min = min(min_score, self._text_weight)
            keyword_ids = {r["chunk_id"] for r in keyword_results}
            filtered = [
                r for r in merged
                if r["chunk_id"] in keyword_ids and r["score"] >= relaxed_min
            ]

        # Step 5: MMR 多样性重排序
        if enable_mmr and len(filtered) > 1:
            filtered = _apply_mmr(filtered, self._mmr_lambda, k)
        else:
            filtered = filtered[:k]

        return [
            MemorySearchResult(
                chunk_id=r["chunk_id"],
                path=r.get("path", ""),
                snippet=r.get("snippet", r.get("content", ""))[:SNIPPET_MAX],
                score=r["score"],
                source=r.get("source", "long_term"),
                metadata=r.get("metadata", {}),
            )
            for r in filtered
        ]

    # ── BM25 关键词搜索 ───────────────────────────────────────────────────────

    async def _search_keyword(
        self, query: str, limit: int
    ) -> list[dict]:
        """FTS5 BM25 关键词搜索"""
        fts_query = _build_fts_query(query)
        if not fts_query:
            return []
        try:
            rows = self._db.execute(
                f"""
                SELECT c.chunk_id, c.content, f.path, f.source,
                       f.metadata, c.stored_at,
                       bm25(chunks_fts) AS rank
                FROM chunks_fts
                JOIN chunks c ON chunks_fts.chunk_id = c.chunk_id
                JOIN files f ON c.file_id = f.id
                WHERE chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning(f"MemoryIndexManager: FTS 查询失败 — {e}")
            return []

        results = []
        for row in rows:
            text_score = _bm25_rank_to_score(row["rank"])
            meta = json.loads(row["metadata"] or "{}")
            results.append({
                "chunk_id": row["chunk_id"],
                "path": row["path"],
                "snippet": row["content"][:SNIPPET_MAX],
                "source": row["source"],
                "score": text_score,
                "text_score": text_score,
                "metadata": meta,
                "stored_at": row["stored_at"],
            })
        return results

    # ── 向量搜索 ──────────────────────────────────────────────────────────────

    async def _search_vector(self, query: str, limit: int) -> list[dict]:
        """SQLite 向量 KNN 搜索 (余弦相似度)"""
        if not self._provider:
            return []
        try:
            query_vecs = await self._embed_with_cache([query])
            query_vec = query_vecs[0]
        except Exception as e:
            logger.warning(f"MemoryIndexManager: 查询嵌入失败 — {e}")
            return []

        # 逐行余弦相似度 (sqlite-vec 不可用时降级)
        rows = self._db.execute(
            """
            SELECT c.chunk_id, c.content, c.embedding, c.stored_at,
                   f.path, f.source, f.metadata
            FROM chunks c
            JOIN files f ON c.file_id = f.id
            WHERE c.embedding IS NOT NULL
            """,
        ).fetchall()

        scored = []
        for row in rows:
            emb = _deserialize_vector(row["embedding"])
            if not emb:
                continue
            sim = _cosine_similarity(query_vec, emb)
            if sim <= 0:
                continue
            meta = json.loads(row["metadata"] or "{}")
            scored.append({
                "chunk_id": row["chunk_id"],
                "path": row["path"],
                "snippet": row["content"][:SNIPPET_MAX],
                "source": row["source"],
                "score": sim,
                "vector_score": sim,
                "metadata": meta,
                "stored_at": row["stored_at"],
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    # ── FTS-only 降级路径 ─────────────────────────────────────────────────────

    async def _search_fts_only(
        self, terms: list[str], k: int, min_score: float
    ) -> list[MemorySearchResult]:
        """无嵌入 Provider 时纯 BM25 检索"""
        seen: dict[str, dict] = {}
        for term in terms:
            rows = await self._search_keyword(term, k * 2)
            for r in rows:
                cid = r["chunk_id"]
                if cid not in seen or r["score"] > seen[cid]["score"]:
                    seen[cid] = r

        filtered = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
        filtered = [r for r in filtered if r["score"] >= min_score][:k]
        return [
            MemorySearchResult(
                chunk_id=r["chunk_id"],
                path=r.get("path", ""),
                snippet=r.get("snippet", "")[:SNIPPET_MAX],
                score=r["score"],
                source=r.get("source", "long_term"),
                metadata=r.get("metadata", {}),
            )
            for r in filtered
        ]

    # ── 嵌入缓存 ─────────────────────────────────────────────────────────────

    async def _embed_with_cache(self, texts: list[str]) -> list[list[float]]:
        """带 SQLite 缓存的嵌入生成"""
        if not self._provider:
            raise RuntimeError("No embedding provider")

        results: list[Optional[list[float]]] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            text_hash = hashlib.sha256(text.encode()).hexdigest()
            row = self._db.execute(
                "SELECT embedding FROM embedding_cache WHERE text_hash=? AND provider=?",
                (text_hash, self._provider.name),
            ).fetchone()
            if row:
                results[i] = _deserialize_vector(row["embedding"])
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        if uncached_texts:
            new_embeddings = await self._provider.embed(uncached_texts)
            for idx, (text_idx, text, emb) in enumerate(
                zip(uncached_indices, uncached_texts, new_embeddings)
            ):
                results[text_idx] = emb
                text_hash = hashlib.sha256(text.encode()).hexdigest()
                self._db.execute(
                    """
                    INSERT OR REPLACE INTO embedding_cache
                    (text_hash, embedding, provider, cached_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (text_hash, _serialize_vector(emb), self._provider.name, time.time()),
                )
            self._db.commit()

        return [r for r in results if r is not None]

    # ── SQLITE_READONLY 恢复 ──────────────────────────────────────────────────

    async def _recover_readonly(self) -> None:
        """SQLITE_READONLY 错误 → 关闭并重新打开连接"""
        self._readonly_recovery_count += 1
        logger.warning(
            f"MemoryIndexManager: readonly 恢复 #{self._readonly_recovery_count}"
        )
        try:
            self._db.close()
        except Exception:
            pass
        self._db = _open_db(self._db_path)
        _ensure_schema(self._db)

    # ── 状态查询 ──────────────────────────────────────────────────────────────

    def status(self) -> dict:
        files = self._db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        chunks = self._db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        cache_entries = self._db.execute(
            f"SELECT COUNT(*) FROM {CACHE_TABLE}"
        ).fetchone()[0]
        return {
            "files": files,
            "chunks": chunks,
            "provider": self._provider.name if self._provider else "fts-only",
            "search_mode": "hybrid" if self._provider else "fts-only",
            "cache_entries": cache_entries,
            "readonly_recovery_count": self._readonly_recovery_count,
            "batch_failure_count": self._batch_failure_count,
            "db_path": self._db_path,
        }

    async def close(self) -> None:
        """关闭数据库连接"""
        try:
            self._db.close()
        except Exception:
            pass


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """按字符数分块, 支持重叠"""
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap
    return chunks


def _serialize_vector(vec: list[float]) -> bytes:
    """将 float 列表序列化为 bytes (小端 float32)"""
    import struct
    return struct.pack(f"{len(vec)}f", *vec)


def _deserialize_vector(blob: bytes) -> Optional[list[float]]:
    """将 bytes 反序列化为 float 列表"""
    if not blob:
        return None
    import struct
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob[:n * 4]))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度"""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ─── 单例管理 ─────────────────────────────────────────────────────────────────

_memory_manager: Optional[MemoryIndexManager] = None
_memory_lock = asyncio.Lock()


async def get_memory_manager() -> MemoryIndexManager:
    """获取全局 MemoryIndexManager 单例"""
    global _memory_manager
    if _memory_manager is not None:
        return _memory_manager
    async with _memory_lock:
        if _memory_manager is None:
            _memory_manager = await MemoryIndexManager.create()
            logger.info("MemoryIndexManager: 全局实例已初始化")
    return _memory_manager
