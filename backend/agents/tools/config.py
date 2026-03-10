"""
工具配置管理模块

从环境变量加载配置，提供默认值，验证配置有效性。

基于 Requirements 12.1-12.7 实现。
"""
import os
from typing import Optional, Any
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolConfig:
    """
    工具配置类
    
    从环境变量加载所有工具相关的配置，提供默认值和验证。
    
    Attributes:
        # API Keys
        brave_api_key: Brave Search API Key
        perplexity_api_key: Perplexity API Key
        xai_api_key: xAI (Grok) API Key
        firecrawl_api_key: Firecrawl API Key
        exa_api_key: Exa Search API Key
        
        # Timeout Settings
        default_timeout: 默认超时时间（秒）
        web_search_timeout: Web Search 超时时间（秒）
        web_fetch_timeout: Web Fetch 超时时间（秒）
        browser_timeout: 浏览器操作超时时间（秒）
        bash_timeout: Bash 命令超时时间（秒）
        
        # Cache Settings
        cache_ttl: 缓存 TTL（秒）
        cache_max_size: 缓存最大条目数
        enable_cache: 是否启用缓存
        
        # Content Size Limits
        max_content_size: 最大内容大小（字节）
        max_search_results: 最大搜索结果数
        max_file_size: 最大文件大小（字节）
        
        # Search Provider Priority
        search_provider_priority: 搜索提供商优先级列表
        
        # Browser Settings
        browser_max_sessions: 最大浏览器会话数
        browser_idle_timeout: 浏览器会话空闲超时（秒）
        browser_headless: 是否使用无头模式
        
        # Bash Settings
        bash_max_sessions: 最大 Bash 会话数
        bash_idle_timeout: Bash 会话空闲超时（秒）
        
        # Security Settings
        enable_ssrf_check: 是否启用 SSRF 检查
        enable_content_wrapping: 是否启用外部内容包装
        enable_suspicious_detection: 是否启用可疑模式检测
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
        从环境变量加载配置
        
        读取所有相关的环境变量，如果未设置则使用默认值。
        自动验证配置的有效性。
        
        Returns:
            ToolConfig: 配置实例
        
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
        
        # 验证配置
        config.validate()
        
        return config
    
    @staticmethod
    def _get_int_env(key: str, default: int) -> int:
        """
        从环境变量获取整数值
        
        Args:
            key: 环境变量名
            default: 默认值
        
        Returns:
            int: 环境变量的整数值，如果无效则返回默认值
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
        从环境变量获取布尔值
        
        Args:
            key: 环境变量名
            default: 默认值
        
        Returns:
            bool: 环境变量的布尔值，如果无效则返回默认值
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
        验证配置的有效性
        
        检查所有配置值是否在合理范围内，如果无效则记录警告并使用默认值。
        
        Raises:
            ValueError: 如果配置严重无效（目前仅记录警告）
        """
        # 验证超时设置（必须 > 0）
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
        
        # 验证缓存设置
        if self.cache_ttl <= 0:
            logger.warning(f"Invalid cache_ttl: {self.cache_ttl}, using 3600")
            self.cache_ttl = 3600
        
        if self.cache_max_size <= 0:
            logger.warning(f"Invalid cache_max_size: {self.cache_max_size}, using 1000")
            self.cache_max_size = 1000
        
        # 验证内容大小限制
        if self.max_content_size <= 0:
            logger.warning(f"Invalid max_content_size: {self.max_content_size}, using 5MB")
            self.max_content_size = 5 * 1024 * 1024
        
        if self.max_search_results <= 0:
            logger.warning(f"Invalid max_search_results: {self.max_search_results}, using 10")
            self.max_search_results = 10
        
        if self.max_file_size <= 0:
            logger.warning(f"Invalid max_file_size: {self.max_file_size}, using 10MB")
            self.max_file_size = 10 * 1024 * 1024
        
        # 验证会话限制
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
        
        # 验证搜索提供商优先级
        if not self.search_provider_priority:
            logger.warning("Empty search_provider_priority, using default: ['exa', 'brave', 'ddgs']")
            self.search_provider_priority = ["exa", "brave", "ddgs"]
        
        logger.info("Configuration validated successfully")
    
    def get_api_key(self, provider: str) -> Optional[str]:
        """
        获取指定提供商的 API Key
        
        Args:
            provider: 提供商名称（brave, perplexity, xai, firecrawl, exa）
        
        Returns:
            Optional[str]: API Key，如果未配置则返回 None
        
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
        检查是否配置了指定提供商的 API Key
        
        Args:
            provider: 提供商名称
        
        Returns:
            bool: 如果配置了 API Key 返回 True
        
        Example:
            >>> config = ToolConfig.from_env()
            >>> if config.has_api_key("brave"):
            ...     # 使用 Brave Search
        """
        key = self.get_api_key(provider)
        return key is not None and len(key) > 0
    
    def to_dict(self) -> dict[str, Any]:
        """
        将配置转换为字典
        
        Returns:
            dict: 配置字典（不包含敏感信息如 API Keys）
        
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


# 全局配置实例（单例模式）
_global_config: Optional[ToolConfig] = None


def get_config() -> ToolConfig:
    """
    获取全局配置实例
    
    使用单例模式，确保整个应用只有一个配置实例。
    第一次调用时从环境变量加载配置。
    
    Returns:
        ToolConfig: 全局配置实例
    
    Example:
        >>> from app.agents.tools.config import get_config
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
    重新加载配置
    
    强制从环境变量重新加载配置，用于配置更新后刷新。
    
    Returns:
        ToolConfig: 新的配置实例
    
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
