# -*- coding: utf-8 -*-
"""
Memory Cache for NewsFlash real-time streaming.
Bypasses SQLite DB completely for 0-latency frontend updates.
"""
from collections import deque

# thread-safe deque for storing the latest 1000 CanonicalItem dicts
news_flash_cache = deque(maxlen=1000)
