# -*- coding: utf-8 -*-
import re
from typing import AsyncGenerator, Dict, Any

class BlockReplyPipeline:
    """
    流式块响应处理器 (Streaming Chunk Parser)
    参照 OpenClaw PI Module 彻底解耦 reasoning 发声与 final output
    """
    
    def __init__(self):
        self._in_think_block = False
    
    async def process_stream(self, llm_stream: AsyncGenerator[str, None]) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理原始 LLM 字符串流，剥离并下发独立的 thinking 与 output 事件
        
        Yields:
           {"type": "thinking", "chunk": "..."}
           {"type": "message", "chunk": "..."}
        """
        # 注意: 某些模型可能会产生残缺的 <thin 标签卡在 chunk 末尾
        # 这里为了演示核心思想，做简化的完整标签解析，更严谨的做法需要一个环形缓冲区处理 cross-chunk 标签截断
        # (通常在实际工业级中通过正则表达式流式 matching 或 AST 解析器)
        
        buffer = ""
        async for raw_chunk in llm_stream:
            buffer += raw_chunk
            
            # 使用一个循环解析 buffer，直到无法在此时拆分
            while buffer:
                if not self._in_think_block:
                    start_idx = buffer.find("<think>")
                    # 检查是否有潜在的被截断的 <think>前缀
                    possible_start = buffer.rfind("<")
                    if start_idx != -1:
                        # 成功找到完整标签
                        if start_idx > 0:
                            yield {"type": "message", "chunk": buffer[:start_idx]}
                        self._in_think_block = True
                        buffer = buffer[start_idx + 7:]
                    elif possible_start != -1 and "<think>".startswith(buffer[possible_start:]):
                        # 极有可能 <think> 被截断在这个 chunk 的末尾，先 yield 之前的内容，保留后缀等下一个 chunk
                        if possible_start > 0:
                            yield {"type": "message", "chunk": buffer[:possible_start]}
                            buffer = buffer[possible_start:]
                        # 退出循环等待下一个 raw_chunk 拼接
                        break
                    else:
                        # 没有发现标签，全都是普通内容
                        yield {"type": "message", "chunk": buffer}
                        buffer = ""
                else:
                    end_idx = buffer.find("</think>")
                    possible_end = buffer.rfind("<")
                    if end_idx != -1:
                        # 成功找到闭合标签
                        if end_idx > 0:
                            yield {"type": "thinking", "chunk": buffer[:end_idx]}
                        self._in_think_block = False
                        buffer = buffer[end_idx + 8:]
                    elif possible_end != -1 and "</think>".startswith(buffer[possible_end:]):
                        # 标签被截断在末尾
                        if possible_end > 0:
                            yield {"type": "thinking", "chunk": buffer[:possible_end]}
                            buffer = buffer[possible_end:]
                        # 退出循环等待拼接
                        break
                    else:
                        # 都是思考内容
                        yield {"type": "thinking", "chunk": buffer}
                        buffer = ""
