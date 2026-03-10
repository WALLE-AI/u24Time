"""
工具辅助函数和类
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExtractedContent:
    """提取的网页内容"""
    title: str
    content: str  # HTML snippet or plain text
    url: Optional[str] = None

    def to_markdown(self) -> str:
        """转换为 Markdown"""
        from markdownify import markdownify
        
        # 提取标题
        md = f"# {self.title}\n\n"
        
        # 转换内容
        content_md = markdownify(self.content, heading_style="ATX", strip=["script", "style"])
        md += content_md
        
        if self.url:
            md += f"\n\n---\n*Source: {self.url}*"
            
        return md


class ReadabilityExtractor:
    """网页内容提取器，使用 readability-lxml"""
    
    def extract_article(self, html: str) -> ExtractedContent:
        """从 HTML 中提取文章主体内容"""
        from readability import Document
        
        doc = Document(html)
        title = doc.title()
        summary = doc.summary()  # 这是一个去除了杂质的 HTML 段落
        
        return ExtractedContent(title=title, content=summary)
