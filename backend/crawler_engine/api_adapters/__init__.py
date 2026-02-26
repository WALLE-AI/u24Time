# api_adapters package
from .adapters import (
    ACLEDAdapter,
    GDELTAdapter,
    USGSAdapter,
    NASAFIRMSAdapter,
    OpenSkyAdapter,
    CoinGeckoAdapter,
    FeodoAdapter,
    URLhausAdapter,
    NewsNowAdapter,
)
from .extended_adapters import (
    YahooFinanceAdapter,
    FearGreedAdapter,
    BtcHashrateAdapter,
    HuggingFaceAdapter,
    CloudStatusAdapter,
    NVDAdapter,
    ReliefWebAdapter,
    PolymarketAdapter,
    HackerNewsAdapter,
)

__all__ = [
    # Original adapters
    "ACLEDAdapter", "GDELTAdapter", "USGSAdapter", "NASAFIRMSAdapter",
    "OpenSkyAdapter", "CoinGeckoAdapter", "FeodoAdapter", "URLhausAdapter",
    "NewsNowAdapter",
    # Extended adapters (WorldMonitor-inspired)
    "YahooFinanceAdapter", "FearGreedAdapter", "BtcHashrateAdapter",
    "HuggingFaceAdapter", "CloudStatusAdapter", "NVDAdapter",
    "ReliefWebAdapter", "PolymarketAdapter", "HackerNewsAdapter",
]
