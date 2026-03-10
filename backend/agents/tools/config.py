"""
å·¥å·éç½®ç®¡çæ¨¡å

ä»ç¯å¢åéå è½½éç½®ï¼æä¾é»è®¤å¼ï¼éªè¯éç½®æææ§ã?

åºäº Requirements 12.1-12.7 å®ç°ã?
"""
import os
from typing import Optional, Any
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolConfig:
    """
    å·¥å·éç½®ç±?
    
    ä»ç¯å¢åéå è½½ææå·¥å·ç¸å³çéç½®ï¼æä¾é»è®¤å¼åéªè¯ã?
    
    Attributes:
        # API Keys
        brave_api_key: Brave Search API Key
        perplexity_api_key: Perplexity API Key
        xai_api_key: xAI (Grok) API Key
        firecrawl_api_key: Firecrawl API Key
        exa_api_key: Exa Search API Key
        
        # Timeout Settings
        default_timeout: é»è®¤è¶æ¶æ¶é´ï¼ç§ï¼?
        web_search_timeout: Web Search è¶æ¶æ¶é´ï¼ç§ï¼?
        web_fetch_timeout: Web Fetch è¶æ¶æ¶é´ï¼ç§ï¼?
        browser_timeout: æµè§å¨æä½è¶æ¶æ¶é´ï¼ç§ï¼
        bash_timeout: Bash å½ä»¤è¶æ¶æ¶é´ï¼ç§ï¼?
        
        # Cache Settings
        cache_ttl: ç¼å­ TTLï¼ç§ï¼?
        cache_max_size: ç¼å­æå¤§æ¡ç®æ°
        enable_cache: æ¯å¦å¯ç¨ç¼å­
        
        # Content Size Limits
        max_content_size: æå¤§åå®¹å¤§å°ï¼å­èï¼?
        max_search_results: æå¤§æç´¢ç»ææ°
        max_file_size: æå¤§æä»¶å¤§å°ï¼å­èï¼?
        
        # Search Provider Priority
        search_provider_priority: æç´¢æä¾åä¼åçº§åè¡¨
        
        # Browser Settings
        browser_max_sessions: æå¤§æµè§å¨ä¼è¯æ?
        browser_idle_timeout: æµè§å¨ä¼è¯ç©ºé²è¶æ¶ï¼ç§ï¼
        browser_headless: æ¯å¦ä½¿ç¨æ å¤´æ¨¡å¼
        
        # Bash Settings
        bash_max_sessions: æå¤?Bash ä¼è¯æ?
        bash_idle_timeout: Bash ä¼è¯ç©ºé²è¶æ¶ï¼ç§ï¼?
        
        # Security Settings
        enable_ssrf_check: æ¯å¦å¯ç¨ SSRF æ£æ?
        enable_content_wrapping: æ¯å¦å¯ç¨å¤é¨åå®¹åè£
        enable_suspicious_detection: æ¯å¦å¯ç¨å¯çæ¨¡å¼æ£æµ?
    """
    
    # ========== API Keys ==========
    brave_api_key: Optional[str] = None
    perplexity_api_key: Optional[str] = None
    xai_api_key: Optional[str] = None
    firecrawl_api_key: Optional[str] = None
    exa_api_key: Optional[str] = None
    jina_api_key: Optional[str] = None
    
    # ========== Timeout Settings ==========
    default_timeout: int = 30
    web_search_timeout: int = 30
    web_fetch_timeout: int = 30
    browser_timeout: int = 30
    bash_timeout: int = 30
    
    # ========== Cache Settings ==========
    cache_ttl: int = 3600  # 60 minutes
    cache_max_size: int = 1000
    enable_cache: bool = True
    
    # ========== Content Size Limits ==========
    max_content_size: int = 5 * 1024 * 1024  # 5MB
    max_search_results: int = 10
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    
    # ========== Search Provider Priority ==========
    search_provider_priority: list[str] = field(default_factory=lambda: ["exa", "ddgs"])
    
    # ========== Browser Settings ==========
    browser_max_sessions: int = 5
    browser_idle_timeout: int = 1800  # 30 minutes
    browser_headless: bool = True
    
    # ========== Bash Settings ==========
    bash_max_sessions: int = 10
    bash_idle_timeout: int = 1800  # 30 minutes
    
    # ========== Security Settings ==========
    enable_ssrf_check: bool = True
    enable_content_wrapping: bool = True
    enable_suspicious_detection: bool = True
    
    @classmethod
    def from_env(cls) -> "ToolConfig":
        """
        ä»ç¯å¢åéå è½½éç½?
        
        è¯»åææç¸å³çç¯å¢åéï¼å¦ææªè®¾ç½®åä½¿ç¨é»è®¤å¼ã?
        èªå¨éªè¯éç½®çæææ§ã?
        
        Returns:
            ToolConfig: éç½®å®ä¾
        
        Example:
            >>> config = ToolConfig.from_env()
            >>> config.default_timeout
            30
        """
        config = cls()
        
        # ========== API Keys ==========
        config.brave_api_key = os.getenv("BRAVE_API_KEY")
        config.perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
        config.xai_api_key = os.getenv("XAI_API_KEY")
        config.firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
        config.exa_api_key = os.getenv("EXA_API_KEY")
        config.jina_api_key = os.getenv("JINA_API_KEY")
        
        # ========== Timeout Settings ==========
        config.default_timeout = cls._get_int_env("TOOL_DEFAULT_TIMEOUT", 30)
        config.web_search_timeout = cls._get_int_env("WEB_SEARCH_TIMEOUT", 30)
        config.web_fetch_timeout = cls._get_int_env("WEB_FETCH_TIMEOUT", 30)
        config.browser_timeout = cls._get_int_env("BROWSER_TIMEOUT", 30)
        config.bash_timeout = cls._get_int_env("BASH_TIMEOUT", 30)
        
        # ========== Cache Settings ==========
        config.cache_ttl = cls._get_int_env("CACHE_TTL", 3600)
        config.cache_max_size = cls._get_int_env("CACHE_MAX_SIZE", 1000)
        config.enable_cache = cls._get_bool_env("ENABLE_CACHE", True)
        
        # ========== Content Size Limits ==========
        config.max_content_size = cls._get_int_env("MAX_CONTENT_SIZE", 5 * 1024 * 1024)
        config.max_search_results = cls._get_int_env("MAX_SEARCH_RESULTS", 10)
        config.max_file_size = cls._get_int_env("MAX_FILE_SIZE", 10 * 1024 * 1024)
        
        # ========== Search Provider Priority ==========
        priority_str = os.getenv("SEARCH_PROVIDER_PRIORITY", "exa,ddgs")
        config.search_provider_priority = [p.strip().lower() for p in priority_str.split(",") if p.strip()]
        
        # ========== Browser Settings ==========
        config.browser_max_sessions = cls._get_int_env("BROWSER_MAX_SESSIONS", 5)
        config.browser_idle_timeout = cls._get_int_env("BROWSER_IDLE_TIMEOUT", 1800)
        config.browser_headless = cls._get_bool_env("BROWSER_HEADLESS", True)
        
        # ========== Bash Settings ==========
        config.bash_max_sessions = cls._get_int_env("BASH_MAX_SESSIONS", 10)
        config.bash_idle_timeout = cls._get_int_env("BASH_IDLE_TIMEOUT", 1800)
        
        # ========== Security Settings ==========
        config.enable_ssrf_check = cls._get_bool_env("ENABLE_SSRF_CHECK", True)
        config.enable_content_wrapping = cls._get_bool_env("ENABLE_CONTENT_WRAPPING", True)
        config.enable_suspicious_detection = cls._get_bool_env("ENABLE_SUSPICIOUS_DETECTION", True)
        
        # éªè¯éç½®
        config.validate()
        
        return config
    
    @staticmethod
    def _get_int_env(key: str, default: int) -> int:
        """
        ä»ç¯å¢åéè·åæ´æ°å?
        
        Args:
            key: ç¯å¢åéå?
            default: é»è®¤å?
        
        Returns:
            int: ç¯å¢åéçæ´æ°å¼ï¼å¦ææ æåè¿åé»è®¤å?
        """
        value = os.getenv(key)
        if value is None:
            return default
        
        try:
            return int(value)
        except ValueError:
            logger.warning(
                f"Invalid integer value for {key}: {value}, using default: {default}"
            )
            return default
    
    @staticmethod
    def _get_bool_env(key: str, default: bool) -> bool:
        """
        ä»ç¯å¢åéè·åå¸å°å?
        
        Args:
            key: ç¯å¢åéå?
            default: é»è®¤å?
        
        Returns:
            bool: ç¯å¢åéçå¸å°å¼ï¼å¦ææ æåè¿åé»è®¤å?
        """
        value = os.getenv(key)
        if value is None:
            return default
        
        value_lower = value.lower()
        if value_lower in ["true", "1", "yes", "on"]:
            return True
        elif value_lower in ["false", "0", "no", "off"]:
            return False
        else:
            logger.warning(
                f"Invalid boolean value for {key}: {value}, using default: {default}"
            )
            return default
    
    def validate(self):
        """
        éªè¯éç½®çæææ?
        
        æ£æ¥ææéç½®å¼æ¯å¦å¨åçèå´åï¼å¦ææ æåè®°å½è­¦åå¹¶ä½¿ç¨é»è®¤å¼ã?
        
        Raises:
            ValueError: å¦æéç½®ä¸¥éæ æï¼ç®åä»è®°å½è­¦åï¼?
        """
        # éªè¯è¶æ¶è®¾ç½®ï¼å¿é¡?> 0ï¼?
        if self.default_timeout <= 0:
            logger.warning(f"Invalid default_timeout: {self.default_timeout}, using 30")
            self.default_timeout = 30
        
        if self.web_search_timeout <= 0:
            logger.warning(f"Invalid web_search_timeout: {self.web_search_timeout}, using 30")
            self.web_search_timeout = 30
        
        if self.web_fetch_timeout <= 0:
            logger.warning(f"Invalid web_fetch_timeout: {self.web_fetch_timeout}, using 30")
            self.web_fetch_timeout = 30
        
        if self.browser_timeout <= 0:
            logger.warning(f"Invalid browser_timeout: {self.browser_timeout}, using 30")
            self.browser_timeout = 30
        
        if self.bash_timeout <= 0:
            logger.warning(f"Invalid bash_timeout: {self.bash_timeout}, using 30")
            self.bash_timeout = 30
        
        # éªè¯ç¼å­è®¾ç½®
        if self.cache_ttl <= 0:
            logger.warning(f"Invalid cache_ttl: {self.cache_ttl}, using 3600")
            self.cache_ttl = 3600
        
        if self.cache_max_size <= 0:
            logger.warning(f"Invalid cache_max_size: {self.cache_max_size}, using 1000")
            self.cache_max_size = 1000
        
        # éªè¯åå®¹å¤§å°éå¶
        if self.max_content_size <= 0:
            logger.warning(f"Invalid max_content_size: {self.max_content_size}, using 5MB")
            self.max_content_size = 5 * 1024 * 1024
        
        if self.max_search_results <= 0:
            logger.warning(f"Invalid max_search_results: {self.max_search_results}, using 10")
            self.max_search_results = 10
        
        if self.max_file_size <= 0:
            logger.warning(f"Invalid max_file_size: {self.max_file_size}, using 10MB")
            self.max_file_size = 10 * 1024 * 1024
        
        # éªè¯ä¼è¯éå¶
        if self.browser_max_sessions <= 0:
            logger.warning(f"Invalid browser_max_sessions: {self.browser_max_sessions}, using 5")
            self.browser_max_sessions = 5
        
        if self.browser_idle_timeout <= 0:
            logger.warning(f"Invalid browser_idle_timeout: {self.browser_idle_timeout}, using 1800")
            self.browser_idle_timeout = 1800
        
        if self.bash_max_sessions <= 0:
            logger.warning(f"Invalid bash_max_sessions: {self.bash_max_sessions}, using 10")
            self.bash_max_sessions = 10
        
        if self.bash_idle_timeout <= 0:
            logger.warning(f"Invalid bash_idle_timeout: {self.bash_idle_timeout}, using 1800")
            self.bash_idle_timeout = 1800
        
        # éªè¯æç´¢æä¾åä¼åçº§
        if not self.search_provider_priority:
            logger.warning("Empty search_provider_priority, using default: ['exa', 'brave', 'ddgs']")
            self.search_provider_priority = ["exa", "brave", "ddgs"]
        
        logger.info("Configuration validated successfully")
    
    def get_api_key(self, provider: str) -> Optional[str]:
        """
        è·åæå®æä¾åç API Key
        
        Args:
            provider: æä¾ååç§°ï¼brave, perplexity, xai, firecrawl, exaï¼?
        
        Returns:
            Optional[str]: API Keyï¼å¦ææªéç½®åè¿å?None
        
        Example:
            >>> config = ToolConfig.from_env()
            >>> key = config.get_api_key("brave")
        """
        provider_lower = provider.lower()
        
        if provider_lower == "brave":
            return self.brave_api_key
        elif provider_lower == "perplexity":
            return self.perplexity_api_key
        elif provider_lower in ["xai", "grok"]:
            return self.xai_api_key
        elif provider_lower == "firecrawl":
            return self.firecrawl_api_key
        elif provider_lower == "exa":
            return self.exa_api_key
        elif provider_lower == "jina":
            return self.jina_api_key
        else:
            logger.warning(f"Unknown provider: {provider}")
            return None
    
    def has_api_key(self, provider: str) -> bool:
        """
        æ£æ¥æ¯å¦éç½®äºæå®æä¾åç API Key
        
        Args:
            provider: æä¾ååç§?
        
        Returns:
            bool: å¦æéç½®äº?API Key è¿å True
        
        Example:
            >>> config = ToolConfig.from_env()
            >>> if config.has_api_key("brave"):
            ...     # ä½¿ç¨ Brave Search
        """
        key = self.get_api_key(provider)
        return key is not None and len(key) > 0
    
    def to_dict(self) -> dict[str, Any]:
        """
        å°éç½®è½¬æ¢ä¸ºå­å¸
        
        Returns:
            dict: éç½®å­å¸ï¼ä¸åå«ææä¿¡æ¯å¦?API Keysï¼?
        
        Example:
            >>> config = ToolConfig.from_env()
            >>> config_dict = config.to_dict()
        """
        return {
            # API Keys (masked)
            "brave_api_key": "***" if self.brave_api_key else None,
            "perplexity_api_key": "***" if self.perplexity_api_key else None,
            "xai_api_key": "***" if self.xai_api_key else None,
            "firecrawl_api_key": "***" if self.firecrawl_api_key else None,
            "exa_api_key": "***" if self.exa_api_key else None,
            "jina_api_key": "***" if self.jina_api_key else None,
            
            # Timeout Settings
            "default_timeout": self.default_timeout,
            "web_search_timeout": self.web_search_timeout,
            "web_fetch_timeout": self.web_fetch_timeout,
            "browser_timeout": self.browser_timeout,
            "bash_timeout": self.bash_timeout,
            
            # Cache Settings
            "cache_ttl": self.cache_ttl,
            "cache_max_size": self.cache_max_size,
            "enable_cache": self.enable_cache,
            
            # Content Size Limits
            "max_content_size": self.max_content_size,
            "max_search_results": self.max_search_results,
            "max_file_size": self.max_file_size,
            
            # Search Provider Priority
            "search_provider_priority": self.search_provider_priority,
            
            # Browser Settings
            "browser_max_sessions": self.browser_max_sessions,
            "browser_idle_timeout": self.browser_idle_timeout,
            "browser_headless": self.browser_headless,
            
            # Bash Settings
            "bash_max_sessions": self.bash_max_sessions,
            "bash_idle_timeout": self.bash_idle_timeout,
            
            # Security Settings
            "enable_ssrf_check": self.enable_ssrf_check,
            "enable_content_wrapping": self.enable_content_wrapping,
            "enable_suspicious_detection": self.enable_suspicious_detection,
        }


# å¨å±éç½®å®ä¾ï¼åä¾æ¨¡å¼ï¼
_global_config: Optional[ToolConfig] = None


def get_config() -> ToolConfig:
    """
    è·åå¨å±éç½®å®ä¾
    
    ä½¿ç¨åä¾æ¨¡å¼ï¼ç¡®ä¿æ´ä¸ªåºç¨åªæä¸ä¸ªéç½®å®ä¾ã?
    ç¬¬ä¸æ¬¡è°ç¨æ¶ä»ç¯å¢åéå è½½éç½®ã?
    
    Returns:
        ToolConfig: å¨å±éç½®å®ä¾
    
    Example:
        >>> from agents.tools.config import get_config
        >>> config = get_config()
        >>> timeout = config.default_timeout
    """
    global _global_config
    
    if _global_config is None:
        _global_config = ToolConfig.from_env()
        logger.info("Global tool configuration loaded")
    
    return _global_config


def reload_config() -> ToolConfig:
    """
    éæ°å è½½éç½®
    
    å¼ºå¶ä»ç¯å¢åééæ°å è½½éç½®ï¼ç¨äºéç½®æ´æ°åå·æ°ã?
    
    Returns:
        ToolConfig: æ°çéç½®å®ä¾
    
    Example:
        >>> import os
        >>> os.environ["TOOL_DEFAULT_TIMEOUT"] = "60"
        >>> config = reload_config()
        >>> config.default_timeout
        60
    """
    global _global_config
    
    _global_config = ToolConfig.from_env()
    logger.info("Global tool configuration reloaded")
    
    return _global_config
