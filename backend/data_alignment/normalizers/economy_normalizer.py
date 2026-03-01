# -*- coding: utf-8 -*-
"""
Economy Normalizer — 经济域数据标准化器
覆盖: stock / futures / quant / crypto / trade 子域
来源: TradingAgents-CN, worldmonitor/market, worldmonitor/economic, worldmonitor/trade
"""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from typing import Optional

from data_alignment.schema import (
    CanonicalItem, SourceType, SeverityLevel, DomainType, SubDomainType,
    EconomicMetadata, HotnessCalculator,
)


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _make_id(*parts: str) -> str:
    raw = ":".join(str(p) for p in parts)
    return hashlib.md5(raw.encode()).hexdigest()[:16]


class EconomyNormalizer:
    """统一经济域标准化入口"""

    # ──────────────────────────────────────────────────────────────
    # Stock: Yahoo Finance chart API
    # ──────────────────────────────────────────────────────────────
    def normalize_yahoo_chart(self, symbol: str, data: dict, source_id: str = "") -> Optional[CanonicalItem]:
        """Yahoo Finance v8/finance/chart/{symbol} 响应 → CanonicalItem"""
        try:
            result = data.get("chart", {}).get("result", [{}])[0]
            meta = result.get("meta", {})
            price = meta.get("regularMarketPrice")
            prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
            currency = meta.get("currency", "USD")
            exchange = meta.get("exchangeName", "")
            name = meta.get("shortName") or meta.get("longName") or symbol

            change_pct = None
            if price and prev_close:
                change_pct = round((price - prev_close) / prev_close * 100, 4)

            eco = EconomicMetadata(
                symbol=symbol, price=price, change_pct=change_pct,
                currency=currency, exchange=exchange,
            )

            severity = SeverityLevel.INFO
            if change_pct is not None:
                if abs(change_pct) >= 5:
                    severity = SeverityLevel.HIGH
                elif abs(change_pct) >= 2:
                    severity = SeverityLevel.MEDIUM

            direction = "▲" if (change_pct or 0) >= 0 else "▼"
            pct_str = f"{direction}{abs(change_pct):.2f}%" if change_pct is not None else ""
            title = f"{name} ({symbol}) {price} {currency} {pct_str}".strip()

            sid = source_id or f"economy.stock.{symbol.lower()}"
            return CanonicalItem(
                item_id=_make_id(sid, symbol, str(price)),
                source_id=sid,
                source_type=SourceType.MARKET,
                domain=DomainType.ECONOMY,
                sub_domain=None,  # Enriched by pipeline from registry config
                title=title,
                url=f"https://finance.yahoo.com/quote/{symbol}",
                published_at=_now_dt(),
                crawled_at=_now_dt(),
                severity_level=severity,
                raw_metadata={"economic": eco.to_dict()},
                categories=["stock", "price"],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Stock: AKShare/Eastmoney A股快照
    # ──────────────────────────────────────────────────────────────
    def normalize_akshare_spot(self, row: dict, source_id: str = "economy.stock.akshare_a") -> Optional[CanonicalItem]:
        """AKShare stock_zh_a_spot_em() 行的 dict"""
        try:
            code = str(row.get("代码", row.get("code", "")))
            name = str(row.get("名称", row.get("name", code)))
            price = float(row.get("最新价", row.get("price", 0)) or 0)
            change_pct = float(row.get("涨跌幅", row.get("change_percent", 0)) or 0)
            volume = float(row.get("成交量", row.get("volume", 0)) or 0)

            eco = EconomicMetadata(
                symbol=code, price=price, change_pct=change_pct,
                volume=volume, currency="CNY", exchange="SSE" if code.startswith(("6", "9")) else "SZSE",
            )

            direction = "▲" if change_pct >= 0 else "▼"
            title = f"{name} ({code}) ¥{price} {direction}{abs(change_pct):.2f}%"

            severity = SeverityLevel.INFO
            if abs(change_pct) >= 9:
                severity = SeverityLevel.HIGH
            elif abs(change_pct) >= 4:
                severity = SeverityLevel.MEDIUM

            return CanonicalItem(
                item_id=_make_id(source_id, code, str(price)),
                source_id=source_id,
                source_type=SourceType.MARKET,
                domain=DomainType.ECONOMY,
                sub_domain=None,  # Enriched by pipeline
                title=title,
                url=f"https://quote.eastmoney.com/concept/{code}.html",
                published_at=_now_dt(),
                crawled_at=_now_dt(),
                severity_level=severity,
                raw_metadata={"economic": eco.to_dict()},
                categories=["stock", "a-share"],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Crypto: CoinGecko price data
    # ──────────────────────────────────────────────────────────────
    def normalize_coingecko(self, coin: dict, source_id: str = "economy.crypto.coingecko") -> Optional[CanonicalItem]:
        """CoinGecko simple/price item dict format"""
        try:
            coin_id = str(coin.get("coin_id") or coin.get("id") or "unknown")
            symbol = str(coin.get("symbol") or coin_id).upper()
            name = str(coin.get("name") or coin_id.capitalize())
            price = coin.get("current_price") or coin.get("usd")
            change_pct = coin.get("price_change_percentage_24h") or coin.get("usd_24h_change")
            market_cap = coin.get("market_cap") or coin.get("usd_market_cap")
            volume = coin.get("total_volume") or coin.get("usd_24h_vol")

            eco = EconomicMetadata(
                symbol=symbol, price=price, change_pct=change_pct,
                market_cap=market_cap, volume=volume, currency="USD",
                exchange="BINANCE",
            )

            direction = "▲" if (change_pct or 0) >= 0 else "▼"
            pct_str = f"{direction}{abs(change_pct):.2f}%" if change_pct is not None else ""
            title = f"{name} ({symbol}) ${price:,.2f} {pct_str}" if price else f"{name} ({symbol})"

            severity = SeverityLevel.INFO
            if abs(change_pct or 0) >= 10:
                severity = SeverityLevel.HIGH
            elif abs(change_pct or 0) >= 5:
                severity = SeverityLevel.MEDIUM

            return CanonicalItem(
                item_id=_make_id(source_id, symbol, str(price)),
                source_id=source_id,
                source_type=SourceType.MARKET,
                domain=DomainType.ECONOMY,
                sub_domain=None,  # Enriched by pipeline
                title=title,
                url=f"https://www.coingecko.com/en/coins/{coin.get('id', symbol.lower())}",
                published_at=_now_dt(),
                crawled_at=_now_dt(),
                severity_level=severity,
                raw_metadata={"economic": eco.to_dict()},
                categories=["crypto", "price"],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Quant: FRED economic indicator
    # ──────────────────────────────────────────────────────────────
    def normalize_fred_series(self, series_id: str, title: str, observations: list[dict]) -> Optional[CanonicalItem]:
        """FRED API observations list"""
        try:
            if not observations:
                return None
            latest = observations[-1]
            value_str = latest.get("value", ".")
            if value_str == ".":
                return None
            value = float(value_str)
            date = latest.get("date", "")

            eco = EconomicMetadata(symbol=series_id, price=value, currency="USD")

            return CanonicalItem(
                item_id=_make_id("economy.quant.fred", series_id, date),
                source_id="economy.quant.fred_series",
                source_type=SourceType.MARKET,
                domain=DomainType.ECONOMY,
                sub_domain=None,  # Enriched by pipeline
                title=f"FRED {series_id}: {title} = {value} ({date})",
                url=f"https://fred.stlouisfed.org/series/{series_id}",
                published_at=_now_dt(),
                crawled_at=_now_dt(),
                severity_level=SeverityLevel.INFO,
                raw_metadata={"economic": eco.to_dict(), "series_id": series_id, "date": date},
                categories=["macro", "fred", "indicator"],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Quant: Fear & Greed Index
    # ──────────────────────────────────────────────────────────────
    def normalize_fear_greed(self, data: dict, source_id: str = "economy.quant.fear_greed_index") -> Optional[CanonicalItem]:
        """alternative.me FNG API data dict"""
        try:
            value = int(data.get("value", 50))
            classification = data.get("value_classification", "Neutral")
            ts = data.get("timestamp")
            published = datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else _now_dt()

            severity = SeverityLevel.INFO
            if value <= 20:
                severity = SeverityLevel.HIGH   # Extreme Fear
            elif value >= 80:
                severity = SeverityLevel.MEDIUM  # Extreme Greed

            title = f"恐惧贪婪指数: {value} ({'极端恐惧' if value <= 20 else '极端贪婪' if value >= 80 else '中性/平衡'})"
            
            return CanonicalItem(
                item_id=_make_id(source_id, str(value), published.isoformat()),
                source_id=source_id,
                source_type=SourceType.MARKET,
                domain=DomainType.ECONOMY,
                sub_domain=None,  # Enriched by pipeline
                title=title,
                url="https://alternative.me/crypto/fear-and-greed-index/",
                published_at=published,
                crawled_at=_now_dt(),
                severity_level=severity,
                raw_metadata={"fng": data},
                categories=["market", "sentiment", "crypto"],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Quant: Macro signals verdict (worldmonitor)
    # ──────────────────────────────────────────────────────────────
    def normalize_macro_signals(self, signals: dict, source_id: str = "economy.quant.macro_signals") -> Optional[CanonicalItem]:
        """worldmonitor get-macro-signals verdict dict"""
        try:
            verdict = signals.get("verdict", "UNKNOWN")
            score = signals.get("score", 0)

            severity_map = {"CASH": SeverityLevel.HIGH, "UNCERTAINTY": SeverityLevel.MEDIUM, "BUY": SeverityLevel.INFO, "HOLD": SeverityLevel.INFO}
            severity = severity_map.get(verdict.upper(), SeverityLevel.INFO)

            eco = EconomicMetadata(symbol="MACRO", signal=verdict, indicators=signals.get("inputs", {}))

            return CanonicalItem(
                item_id=_make_id(source_id, verdict, str(score)),
                source_id=source_id,
                source_type=SourceType.MARKET,
                domain=DomainType.ECONOMY,
                sub_domain=None,  # Enriched by pipeline
                title=f"宏观信号: {verdict} (score={score:.1f})",
                url="https://worldmonitor.app",
                published_at=_now_dt(),
                crawled_at=_now_dt(),
                severity_level=severity,
                raw_metadata={"economic": eco.to_dict(), "signals": signals},
                categories=["macro", "signal", "quant"],
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Trade: WTO trade flow record
    # ──────────────────────────────────────────────────────────────
    def normalize_wto_trade(self, flow: dict, source_id: str = "economy.trade.wto_flows") -> Optional[CanonicalItem]:
        """worldmonitor TradeFlowRecord dict"""
        try:
            reporter = flow.get("reportingCountry", "")
            partner = flow.get("partnerCountry", "")
            year = flow.get("year", "")
            exports = flow.get("exportValueUsd", 0)
            imports = flow.get("importValueUsd", 0)
            yoy = flow.get("yoyExportChange", 0)

            title = f"WTO Trade: {reporter}↔{partner} ({year}) Exp=${exports/1e9:.1f}B Imp=${imports/1e9:.1f}B YoY={yoy:+.1f}%"

            severity = SeverityLevel.INFO
            if abs(yoy) >= 20:
                severity = SeverityLevel.HIGH
            elif abs(yoy) >= 10:
                severity = SeverityLevel.MEDIUM

            return CanonicalItem(
                item_id=_make_id(source_id, reporter, partner, str(year)),
                source_id=source_id,
                source_type=SourceType.MARKET,
                domain=DomainType.ECONOMY,
                sub_domain=None,  # Enriched by pipeline
                title=title,
                url="https://timeseries.wto.org",
                published_at=_now_dt(),
                crawled_at=_now_dt(),
                severity_level=severity,
                raw_metadata={"flow": flow},
                categories=["wto", "trade", "bilateral"],
            )
        except Exception:
            return None


    # ──────────────────────────────────────────────────────────────
    # Quant: Bitcoin Hashrate (mempool.space)
    # ──────────────────────────────────────────────────────────────
    def normalize_mempool_hashrate(self, data: dict, source_id: str = "economy.quant.mempool_hashrate") -> Optional[CanonicalItem]:
        """mempool.space /api/v1/mining/hashrate/1m response"""
        try:
            hashrates = data.get("hashrates") or data.get("currentHashrate")
            if isinstance(hashrates, list) and len(hashrates) >= 2:
                recent = float(hashrates[-1].get("avgHashrate", 0))
                older = float(hashrates[0].get("avgHashrate", 1))
                change_pct = (recent - older) / older * 100 if older else 0
                hashrate_eh = recent / 1e18  # EH/s
            elif isinstance(hashrates, (int, float)):
                recent = float(hashrates)
                change_pct = 0.0
                hashrate_eh = recent / 1e18
            else:
                return None

            severity = SeverityLevel.HIGH if change_pct < -10 else (
                       SeverityLevel.MEDIUM if abs(change_pct) > 5 else SeverityLevel.INFO)

            eco = EconomicMetadata(
                symbol="BTC-HASHRATE",
                price=hashrate_eh,
                change_pct=round(change_pct, 2),
                currency="EH/s",
                exchange="mempool.space",
            )

            return CanonicalItem(
                item_id=_make_id(source_id, f"{hashrate_eh:.2f}"),
                source_id=source_id,
                source_type=SourceType.MARKET,
                domain=DomainType.ECONOMY,
                sub_domain=None,  # Enriched by pipeline
                title=f"Bitcoin Hashrate: {hashrate_eh:.2f} EH/s ({change_pct:+.1f}% 30d)",
                url="https://mempool.space/mining",
                published_at=_now_dt(),
                crawled_at=_now_dt(),
                severity_level=severity,
                raw_metadata={"economic": eco.to_dict(), "hashrate_30d_change_pct": change_pct},
                categories=["bitcoin", "hashrate", "mining"],
            )
        except Exception:
            return None


economy_normalizer = EconomyNormalizer()
