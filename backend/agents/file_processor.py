"""File processor for handling multimodal file uploads.

This module processes uploaded files (images, videos, audio, documents)
and prepares them for consumption by LLM models.

Enhanced with MarkItDown support for better document format compatibility.
Reference: https://github.com/microsoft/markitdown
"""

from dataclasses import dataclass
from typing import Literal, Optional
from collections import OrderedDict
from pathlib import Path
import base64
import io
import logging
import tempfile
import os
from PIL import Image
import PyPDF2
import docx

from agents.file_errors import (
    FileProcessingError,
    FileSizeError,
    FileTypeError,
    FileDownloadError,
    FileParsingError,
)

logger = logging.getLogger(__name__)

# Try to import MarkItDown (optional dependency)
try:
    from markitdown import MarkItDown
    MARKITDOWN_AVAILABLE = True
    logger.info("MarkItDown is available for enhanced document processing")
except ImportError:
    MARKITDOWN_AVAILABLE = False
    logger.info("MarkItDown not available, using fallback document processing")


@dataclass
class ProcessedFile:
    """Processed file ready for LLM consumption."""
    mime_type: str
    filename: str
    content_type: Literal['base64', 'text', 'error']
    content: str
    metadata: dict


class LRUCache:
    """LRU cache with size and count limits."""
    
    def __init__(self, max_files: int = 40, max_size_bytes: int = 20 * 1024 * 1024):
        """Initialize LRU cache.
        
        Args:
            max_files: Maximum number of files to cache
            max_size_bytes: Maximum total size in bytes (default 20MB)
        """
        self.max_files = max_files
        self.max_size_bytes = max_size_bytes
        self.cache = OrderedDict()  # url -> (content, size)
        self.total_size = 0
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> bytes | None:
        """Get item from cache.
        
        Args:
            key: Cache key (URL)
            
        Returns:
            Cached content or None if not found
        """
        if key in self.cache:
            # Move to end (most recently used)
            self.cache.move_to_end(key)
            self.hits += 1
            return self.cache[key][0]
        else:
            self.misses += 1
            return None
    
    def put(self, key: str, value: bytes) -> None:
        """Put item in cache with LRU eviction.
        
        Args:
            key: Cache key (URL)
            value: Content to cache
        """
        size = len(value)
        
        # If item already exists, remove it first
        if key in self.cache:
            old_size = self.cache[key][1]
            self.total_size -= old_size
            del self.cache[key]
        
        # Evict items if necessary
        while (len(self.cache) >= self.max_files or 
               self.total_size + size > self.max_size_bytes) and self.cache:
            # Remove least recently used item (first item)
            oldest_key, (_, oldest_size) = self.cache.popitem(last=False)
            self.total_size -= oldest_size
            logger.debug(f"LRU evicted: {oldest_key} ({oldest_size} bytes)")
        
        # Add new item
        self.cache[key] = (value, size)
        self.total_size += size
        logger.debug(f"LRU cached: {key} ({size} bytes), total: {self.total_size} bytes, count: {len(self.cache)}")
    
    def clear(self) -> None:
        """Clear all cached items."""
        self.cache.clear()
        self.total_size = 0
        logger.info(f"Cache cleared. Stats - Hits: {self.hits}, Misses: {self.misses}")
    
    def get_stats(self) -> dict:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache stats
        """
        return {
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': self.hits / (self.hits + self.misses) if (self.hits + self.misses) > 0 else 0,
            'size': self.total_size,
            'count': len(self.cache),
            'max_files': self.max_files,
            'max_size_bytes': self.max_size_bytes
        }


class FileProcessor:
    """Process uploaded files for agent consumption.
    
    Enhanced with MarkItDown support for better document format compatibility.
    """
    
    def __init__(self, oss_client, max_size: int = 20 * 1024 * 1024, use_markitdown: bool = True, db=None):
        """Initialize FileProcessor.
        
        Args:
            oss_client: OSS client for downloading files
            max_size: Maximum file size in bytes (default 20MB)
            use_markitdown: Whether to use MarkItDown for document processing (default True)
            db: Optional AsyncSession for DB-backed local path lookup
        """
        self.oss_client = oss_client
        self.max_size = max_size
        self.db = db  # Optional DB session for local_path lookup
        self.file_cache = LRUCache(max_files=40, max_size_bytes=20 * 1024 * 1024)
        
        # Cache statistics for three-tier caching strategy
        self.cache_stats = {"memory_cache": 0, "local_file": 0, "oss_download": 0}
        self.call_count = 0
        
        # Initialize MarkItDown if available and enabled
        self.use_markitdown = use_markitdown and MARKITDOWN_AVAILABLE
        if self.use_markitdown:
            self.markitdown = MarkItDown()
            logger.info("FileProcessor initialized with MarkItDown support")
        else:
            self.markitdown = None
            if use_markitdown and not MARKITDOWN_AVAILABLE:
                logger.warning("MarkItDown requested but not available, using fallback")
    
    async def process_file_part(self, file_part: dict) -> ProcessedFile:
        """Process a FilePart into format suitable for LLM.
        
        Args:
            file_part: Dictionary with 'mime', 'filename', 'url' keys
            
        Returns:
            ProcessedFile with content ready for LLM
        """
        mime_type = file_part['mime']
        filename = file_part['filename']
        url = file_part['url']
        
        logger.info(f"Processing file: {filename} ({mime_type})")
        
        try:
            # Download file from OSS
            file_content = await self._download_file(url)
            
            if file_content is None:
                raise FileDownloadError(
                    f"Failed to download file from OSS",
                    filename=filename,
                    url=url
                )
            
            # Check size
            if len(file_content) > self.max_size:
                raise FileSizeError(
                    f"File too large: {len(file_content)} bytes (max {self.max_size})",
                    filename=filename,
                    size=len(file_content),
                    max_size=self.max_size
                )
            
            # Process based on type and add URL to metadata
            if mime_type.startswith('image/'):
                result = await self._process_image(file_content, mime_type, filename)
            elif mime_type.startswith('video/'):
                result = await self._process_video(file_content, mime_type, filename)
            elif mime_type.startswith('audio/'):
                result = await self._process_audio(file_content, mime_type, filename)
            elif self._is_document_type(mime_type):
                result = await self._process_document_smart(file_content, mime_type, filename)
            else:
                raise FileTypeError(
                    f"Unsupported file type: {mime_type}",
                    filename=filename,
                    mime_type=mime_type
                )
            
            # 🆕 Add URL to metadata for all successful processing
            result.metadata['url'] = url
            result.metadata['oss_url'] = url
            return result
        
        except FileSizeError as e:
            logger.warning(f"File size error: {e.message}", extra={
                "file_name": e.filename,
                "file_size": e.size,
                "max_size": e.max_size
            })
            return ProcessedFile(
                mime_type=mime_type,
                filename=filename,
                content_type='error',
                content=e.message,
                metadata={
                    'error_type': 'size_error',
                    'retryable': e.retryable,
                    'size': e.size,
                    'max_size': e.max_size
                }
            )
        
        except FileTypeError as e:
            logger.warning(f"File type error: {e.message}", extra={
                "file_name": e.filename,
                "mime_type": e.mime_type
            })
            return ProcessedFile(
                mime_type=mime_type,
                filename=filename,
                content_type='error',
                content=e.message,
                metadata={
                    'error_type': 'type_error',
                    'retryable': e.retryable,
                    'mime_type': e.mime_type
                }
            )
        
        except FileDownloadError as e:
            logger.error(f"File download error: {e.message}", extra={
                "file_name": e.filename,
                "file_url": e.url
            })
            return ProcessedFile(
                mime_type=mime_type,
                filename=filename,
                content_type='error',
                content=e.message,
                metadata={
                    'error_type': 'download_error',
                    'retryable': e.retryable,
                    'url': e.url
                }
            )
        
        except FileParsingError as e:
            logger.error(f"File parsing error: {e.message}", extra={
                "file_name": e.filename,
                "file_type": e.file_type
            })
            return ProcessedFile(
                mime_type=mime_type,
                filename=filename,
                content_type='error',
                content=e.message,
                metadata={
                    'error_type': 'parsing_error',
                    'retryable': e.retryable,
                    'file_type': e.file_type
                }
            )
        
        except Exception as e:
            logger.exception(f"Unexpected error processing file: {filename}")
            return ProcessedFile(
                mime_type=mime_type,
                filename=filename,
                content_type='error',
                content=f"Failed to process file: {str(e)}",
                metadata={
                    'error_type': 'unknown',
                    'retryable': False
                }
            )
    
    def cleanup_cache(self) -> dict:
        """Clean up file cache and return final statistics.
        
        Should be called at session end to free memory.
        
        Returns:
            Dictionary with final cache statistics
        """
        stats = self.file_cache.get_stats()
        logger.info(f"Cleaning up file cache. Final stats: {stats}")
        self.file_cache.clear()
        return stats
    
    def get_cache_stats(self) -> dict:
        """Get current cache statistics.
        
        Returns:
            Dictionary with cache stats
        """
        return self.file_cache.get_stats()
    
    async def _download_file(self, url: str) -> bytes | None:
        """Download file from OSS with three-tier caching strategy.
        
        Caching layers:
        1. Memory LRU cache (fastest, <1ms)
        2. Local file system (fast, 10-50ms)
        3. OSS download (slowest, 100-1000ms)
        
        Args:
            url: File URL
            
        Returns:
            File content as bytes, or None if download fails
            
        Raises:
            FileDownloadError: If download fails
        """
        self.call_count += 1
        
        # Layer 1: Check memory LRU cache
        cached_content = self.file_cache.get(url)
        if cached_content is not None:
            self.cache_stats["memory_cache"] += 1
            logger.debug(f"Memory cache hit for {url}")
            self._log_cache_stats()
            return cached_content
        
        # Layer 2: Check local file system
        enable_local_cache = os.getenv("ENABLE_LOCAL_FILE_CACHE", "true").lower() == "true"
        if enable_local_cache:
            local_path = await self._get_local_path(url)
            if local_path and local_path.exists():
                try:
                    file_content = local_path.read_bytes()
                    # Verify file integrity
                    if len(file_content) > 0:
                        self.cache_stats["local_file"] += 1
                        # Add to memory cache
                        self.file_cache.put(url, file_content)
                        logger.info(f"Local file cache hit: {local_path}")
                        self._log_cache_stats()
                        return file_content
                except Exception as e:
                    logger.warning(f"Local file read failed, falling back to OSS download: {e}")
        
        # Layer 3: Download from OSS
        logger.info(f"Downloading from OSS: {url}")
        try:
            # Extract object name from URL
            object_name = self._extract_object_name(url)
            
            # Download from OSS
            file_obj = await self.oss_client.get_object(object_name)
            
            if file_obj is None:
                logger.error(f"Failed to get object {object_name} from OSS")
                return None
            
            content = file_obj['Body']
            self.cache_stats["oss_download"] += 1
            
            # Save to local cache (optional, failure doesn't affect return)
            if enable_local_cache:
                try:
                    local_path = await self._get_local_path(url)
                    if local_path:
                        self._save_to_local_cache(content, local_path)
                        logger.info(f"File saved to local cache: {local_path}")
                except Exception as e:
                    logger.warning(f"Local cache save failed: {e}")
            
            # Add to memory cache
            self.file_cache.put(url, content)
            logger.debug(f"Downloaded and cached {url}")
            
            self._log_cache_stats()
            return content
        except Exception as e:
            logger.error(f"Error downloading file from {url}: {str(e)}")
            return None
    
    async def _get_local_path(self, file_url: str) -> Path | None:
        """Resolve local file path using dual-source lookup.

        Strategy:
        1. Query DB File.metadata_['local_path'] for the exact path recorded at upload time
           (works for workspace-relative paths that differ per user).
        2. Fall back to URL-based derivation (legacy / backward compatibility).

        Args:
            file_url: OSS file URL (http/https or oss://)

        Returns:
            Local file path, or None if not resolvable
        """
        # --- Strategy 1: DB lookup ---
        if self.db is not None:
            try:
                from sqlalchemy import select as sa_select
                from app.models.file import File as FileModel
                from urllib.parse import urlparse, unquote
                import re as _re

                # Match by oss_url or storage_path stored in metadata_
                result = await self.db.execute(
                    sa_select(FileModel).order_by(FileModel.created_at.desc()).limit(200)
                )
                records = result.scalars().all()
                
                parsed = urlparse(file_url)
                url_decoded_path = unquote(parsed.path)
                url_basename = url_decoded_path.split("/")[-1]
                stripped_url_basename = _re.sub(r"^\d+_", "", url_basename)
                
                file_record = None
                
                # 双匹配逻辑
                for rec in records:
                    meta = rec.metadata_ or {}
                    # 1. 直接匹配 oss_url
                    if meta.get("oss_url") == file_url:
                        file_record = rec
                        break
                        
                    # 2. 匹配 basename
                    obj_name = meta.get("object_name", "")
                    stored_basename = obj_name.split("/")[-1] if obj_name else ""
                    
                    if stored_basename and stored_basename == url_basename:
                        file_record = rec
                        break
                        
                    # 3. 兜底匹配原始文件名
                    if rec.filename and rec.filename == stripped_url_basename:
                        file_record = rec
                        # 继续寻找精确匹配

                if file_record:
                    meta = file_record.metadata_ or {}
                    local_path_str = meta.get("local_path")
                    if local_path_str:
                        p = Path(local_path_str)
                        logger.debug(f"DB local_path lookup succeeded: {p}")
                        return p
            except Exception as e:
                logger.debug(f"DB local_path lookup failed, falling back to URL derivation: {e}")

        # --- Strategy 2: URL-based derivation (legacy) ---
        return self._get_local_path_from_url(file_url)

    def _get_local_path_from_url(self, file_url: str) -> Path | None:
        """Derive local path from OSS URL (legacy / backward-compatible).
        
        URL format examples:
        - https://oss.example.com/papergen/user123/session456/1704067200_report.pdf
        - https://oss.example.com/papergen/user123/uploads/1704067200_image.jpg
        
        Local path format:
        - workspace_uploads/user123/session456/1704067200_report.pdf
        - workspace_uploads/user123/uploads/1704067200_image.jpg
        
        Args:
            file_url: File URL
            
        Returns:
            Local file path, or None if URL cannot be parsed
        """
        try:
            from urllib.parse import urlparse, unquote
            
            parsed = urlparse(file_url)
            path_parts = parsed.path.strip("/").split("/")
            
            # Find "papergen" path segment
            if "papergen" in path_parts:
                papergen_index = path_parts.index("papergen")
                # papergen/{user_id}/{session_id or uploads}/{filename}
                if len(path_parts) > papergen_index + 3:
                    user_id = path_parts[papergen_index + 1]
                    session_or_uploads = path_parts[papergen_index + 2]
                    filename = unquote(path_parts[papergen_index + 3])
                    
                    workspace_dir = os.getenv("WORKSPACE_UPLOADS_DIR", "./workspace_uploads")
                    local_path = Path(workspace_dir) / user_id / session_or_uploads / filename
                    return local_path
        except Exception as e:
            logger.debug(f"Cannot extract local path from URL: {file_url}, error: {e}")
        
        return None
    
    def _save_to_local_cache(self, file_content: bytes, local_path: Path) -> None:
        """Save file to local cache.
        
        Args:
            file_content: File content
            local_path: Local file path
            
        Raises:
            OSError: If file save fails
        """
        # Create directory
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save file
        local_path.write_bytes(file_content)
        
        # Verify file integrity
        if local_path.stat().st_size != len(file_content):
            raise OSError(f"File save incomplete: {local_path}")
    
    def _log_cache_stats(self) -> None:
        """Log cache statistics (every 10 calls)."""
        if self.call_count % 10 == 0:
            total = sum(self.cache_stats.values())
            if total > 0:
                memory_rate = self.cache_stats["memory_cache"] / total
                local_rate = self.cache_stats["local_file"] / total
                oss_rate = self.cache_stats["oss_download"] / total
                logger.info(
                    f"Cache stats (total: {total}) - "
                    f"Memory: {self.cache_stats['memory_cache']} ({memory_rate:.1%}), "
                    f"Local: {self.cache_stats['local_file']} ({local_rate:.1%}), "
                    f"OSS: {self.cache_stats['oss_download']} ({oss_rate:.1%})"
                )
    
    async def _process_image(self, content: bytes, mime_type: str, filename: str) -> ProcessedFile:
        """Process image file.
        
        Args:
            content: Image file content
            mime_type: MIME type
            filename: Original filename
            
        Returns:
            ProcessedFile with base64-encoded image
            
        Raises:
            FileParsingError: If image processing fails
        """
        try:
            # Compress if too large
            if len(content) > 5 * 1024 * 1024:  # 5MB
                logger.info(f"Compressing large image: {filename}")
                content = await self._compress_image(content)
            
            # Encode to base64
            base64_content = base64.b64encode(content).decode('utf-8')
            
            # Get image metadata
            image = Image.open(io.BytesIO(content))
            metadata = {
                'width': image.width,
                'height': image.height,
                'format': image.format,
                'size': len(content)
            }
            
            logger.info(f"Successfully processed image: {filename} ({metadata})")
            
            return ProcessedFile(
                mime_type=mime_type,
                filename=filename,
                content_type='base64',
                content=base64_content,
                metadata=metadata
            )
        except Exception as e:
            logger.error(f"Failed to process image {filename}: {str(e)}")
            raise FileParsingError(
                f"Failed to process image: {str(e)}",
                filename=filename,
                file_type='image'
            )
    
    async def _process_video(self, content: bytes, mime_type: str, filename: str) -> ProcessedFile:
        """Process video file - extract first frame.
        
        Args:
            content: Video file content
            mime_type: MIME type
            filename: Original filename
            
        Returns:
            ProcessedFile with base64-encoded thumbnail
            
        Raises:
            FileParsingError: If video processing fails
        """
        temp_path = None
        try:
            import cv2
            
            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as temp_file:
                temp_path = temp_file.name
                temp_file.write(content)
            
            # Extract first frame
            cap = cv2.VideoCapture(temp_path)
            
            # Get video metadata first
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            # Calculate duration
            duration = frame_count / fps if fps > 0 else 0
            
            ret, frame = cap.read()
            cap.release()
            
            if not ret:
                raise ValueError("Failed to extract frame from video")
            
            # Convert to JPEG
            _, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            
            # Compress if needed
            if len(frame_bytes) > 1024 * 1024:  # 1MB
                logger.info(f"Compressing video thumbnail: {filename}")
                frame_bytes = await self._compress_image(frame_bytes)
            
            base64_content = base64.b64encode(frame_bytes).decode('utf-8')
            
            metadata = {
                'duration': duration,
                'width': width,
                'height': height,
                'thumbnail_size': len(frame_bytes)
            }
            
            logger.info(f"Successfully processed video: {filename} ({metadata})")
            
            return ProcessedFile(
                mime_type='image/jpeg',  # Thumbnail is JPEG
                filename=f"{filename}_thumbnail.jpg",
                content_type='base64',
                content=base64_content,
                metadata=metadata
            )
        except Exception as e:
            logger.error(f"Failed to process video {filename}: {str(e)}")
            raise FileParsingError(
                f"Failed to process video: {str(e)}",
                filename=filename,
                file_type='video'
            )
        finally:
            # Clean up temp file
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception as e:
                    logger.warning(f"Failed to delete temp file {temp_path}: {str(e)}")
    
    async def _process_audio(self, content: bytes, mime_type: str, filename: str) -> ProcessedFile:
        """Process audio file.
        
        Args:
            content: Audio file content
            mime_type: MIME type
            filename: Original filename
            
        Returns:
            ProcessedFile with base64-encoded audio
            
        Raises:
            FileParsingError: If audio processing fails
        """
        try:
            # For now, just encode to base64
            # TODO: Add audio transcription support
            base64_content = base64.b64encode(content).decode('utf-8')
            
            metadata = {'size': len(content)}
            
            logger.info(f"Successfully processed audio: {filename} ({metadata})")
            
            return ProcessedFile(
                mime_type=mime_type,
                filename=filename,
                content_type='base64',
                content=base64_content,
                metadata=metadata
            )
        except Exception as e:
            logger.error(f"Failed to process audio {filename}: {str(e)}")
            raise FileParsingError(
                f"Failed to process audio: {str(e)}",
                filename=filename,
                file_type='audio'
            )
    
    async def _process_document(self, content: bytes, mime_type: str, filename: str) -> ProcessedFile:
        """Process document file - extract text.
        
        Args:
            content: Document file content
            mime_type: MIME type
            filename: Original filename
            
        Returns:
            ProcessedFile with extracted text
            
        Raises:
            FileParsingError: If document processing fails
        """
        try:
            if mime_type == 'application/pdf':
                text = self._extract_pdf_text(content)
            elif mime_type == 'text/plain' or mime_type == 'text/markdown':
                try:
                    text = content.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        text = content.decode('utf-16')
                    except UnicodeDecodeError:
                        try:
                            text = content.decode('gbk')
                        except UnicodeDecodeError:
                            text = content.decode('utf-8', errors='ignore')
            elif 'wordprocessingml' in mime_type:
                text = self._extract_docx_text(content)
            else:
                raise ValueError(f"Unsupported document type: {mime_type}")
            
            # Truncate if too long
            max_chars = 50000
            truncated = False
            if len(text) > max_chars:
                text = text[:max_chars] + "\n\n...(content truncated)"
                truncated = True
            
            metadata = {
                'char_count': len(text),
                'truncated': truncated
            }
            
            logger.info(f"Successfully processed document: {filename} ({metadata})")
            
            return ProcessedFile(
                mime_type=mime_type,
                filename=filename,
                content_type='text',
                content=text,
                metadata=metadata
            )
        except Exception as e:
            logger.error(f"Failed to process document {filename}: {str(e)}")
            raise FileParsingError(
                f"Failed to process document: {str(e)}",
                filename=filename,
                file_type='document'
            )
    
    def _extract_pdf_text(self, content: bytes) -> str:
        """Extract text from PDF.
        
        Args:
            content: PDF file content
            
        Returns:
            Extracted text
        """
        pdf_file = io.BytesIO(content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = []
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text.append(page_text)
        return '\n\n'.join(text)
    
    def _extract_docx_text(self, content: bytes) -> str:
        """Extract text from DOCX.
        
        Args:
            content: DOCX file content
            
        Returns:
            Extracted text
        """
        doc_file = io.BytesIO(content)
        doc = docx.Document(doc_file)
        text = []
        for paragraph in doc.paragraphs:
            if paragraph.text:
                text.append(paragraph.text)
        return '\n\n'.join(text)
    
    async def _compress_image(self, content: bytes) -> bytes:
        """Compress image to reduce size.
        
        Args:
            content: Image content
            
        Returns:
            Compressed image content
        """
        image = Image.open(io.BytesIO(content))
        
        # Convert RGBA to RGB if necessary
        if image.mode == 'RGBA':
            # Create a white background
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3])  # Use alpha channel as mask
            image = background
        elif image.mode not in ('RGB', 'L'):
            image = image.convert('RGB')
        
        # Resize if too large
        max_dimension = 2048
        if max(image.width, image.height) > max_dimension:
            ratio = max_dimension / max(image.width, image.height)
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
        
        # Save with compression
        output = io.BytesIO()
        image.save(output, format='JPEG', quality=85, optimize=True)
        return output.getvalue()
    
    def _extract_object_name(self, url: str) -> str:
        """Extract OSS object name from URL.
        
        Args:
            url: File URL (can be full HTTP URL, oss:// URL, or object name)
            
        Returns:
            Object name for OSS
        """
        # If it's already an object name (no protocol), return as is
        if not url.startswith(('http://', 'https://', 'oss://')):
            return url
        
        # URL format: oss://{bucket}/{object_name}
        if url.startswith('oss://'):
            # Format: oss://bucket/object_name
            parts = url.split('/', 3)
            if len(parts) >= 4:
                return parts[3]
            return url.split('/', 2)[2] if len(url.split('/', 2)) > 2 else url
        
        # URL format: https://{endpoint}/{bucket}/{object_name} or https://{bucket}.{endpoint}/{object_name}
        # Extract from HTTP URL
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path.lstrip('/')
        
        # Remove bucket name prefix if present
        # Path format: {bucket}/{object_name} or just {object_name}
        if path.startswith(f"{self.oss_client.bucket}/"):
            path = path[len(self.oss_client.bucket) + 1:]
        
        return path
    
    def _is_document_type(self, mime_type: str) -> bool:
        """Check if mime type is a supported document type.
        
        Args:
            mime_type: MIME type to check
            
        Returns:
            True if supported document type
        """
        # Basic document types (always supported)
        basic_types = [
            'application/pdf',
            'text/plain',
            'text/markdown',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # DOCX
        ]
        
        # Extended types (supported with MarkItDown)
        extended_types = [
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',  # PPTX
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # XLSX
            'application/vnd.ms-excel',  # XLS
            'text/html',
            'text/csv',
            'application/json',
            'application/xml',
            'text/xml',
            'application/epub+zip',  # EPUB
        ]
        
        if mime_type in basic_types:
            return True
        
        if self.use_markitdown and mime_type in extended_types:
            return True
        
        return False
    
    async def _process_document_smart(self, content: bytes, mime_type: str, filename: str) -> ProcessedFile:
        """Smart document processing with MarkItDown fallback.
        
        Args:
            content: Document file content
            mime_type: MIME type
            filename: Original filename
            
        Returns:
            ProcessedFile with extracted text
        """
        # Try MarkItDown first for better results
        if self.use_markitdown and self._should_use_markitdown(mime_type):
            try:
                return await self._process_document_with_markitdown(content, mime_type, filename)
            except Exception as e:
                logger.warning(f"MarkItDown processing failed for {filename}, using fallback: {e}")
        
        # Fallback to original implementation
        return await self._process_document(content, mime_type, filename)
    
    def _should_use_markitdown(self, mime_type: str) -> bool:
        """Determine if MarkItDown should be used for this mime type.
        
        Args:
            mime_type: MIME type to check
            
        Returns:
            True if MarkItDown should be used
        """
        # Always use MarkItDown for these types (better results)
        markitdown_preferred = [
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',  # PPTX
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # XLSX
            'application/vnd.ms-excel',  # XLS
            'text/html',
            'text/csv',
            'application/json',
            'application/xml',
            'text/xml',
            'application/epub+zip',  # EPUB
        ]
        
        # Optionally use MarkItDown for these (may be better)
        markitdown_optional = [
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # DOCX
        ]
        
        return mime_type in markitdown_preferred or mime_type in markitdown_optional
    
    async def _process_document_with_markitdown(self, content: bytes, mime_type: str, filename: str) -> ProcessedFile:
        """Process document using MarkItDown.
        
        Args:
            content: Document file content
            mime_type: MIME type
            filename: Original filename
            
        Returns:
            ProcessedFile with Markdown-formatted text
            
        Raises:
            FileParsingError: If document processing fails
        """
        try:
            # MarkItDown requires file-like object
            file_obj = io.BytesIO(content)
            
            # Get file extension hint
            ext = os.path.splitext(filename)[1].lower()
            
            # Convert to Markdown
            result = self.markitdown.convert_stream(file_obj, file_extension=ext)
            
            # Extract text content (already in Markdown format)
            text = result.text_content
            
            # Truncate if too long
            max_chars = 50000
            truncated = False
            if len(text) > max_chars:
                text = text[:max_chars] + "\n\n...(content truncated)"
                truncated = True
            
            metadata = {
                'char_count': len(text),
                'truncated': truncated,
                'processor': 'markitdown',
                'format': 'markdown'
            }
            
            logger.info(f"Successfully processed document with MarkItDown: {filename} ({metadata})")
            
            return ProcessedFile(
                mime_type=mime_type,
                filename=filename,
                content_type='text',
                content=text,
                metadata=metadata
            )
        except Exception as e:
            logger.error(f"Failed to process document with MarkItDown {filename}: {str(e)}")
            raise FileParsingError(
                f"Failed to process document with MarkItDown: {str(e)}",
                filename=filename,
                file_type='document'
            )


# ========== Rebuild Pydantic Models ==========
# Rebuild ToolContext model after ProcessedFile is defined
try:
    from agents.tools.base import rebuild_tool_context_model
    rebuild_tool_context_model()
except Exception as e:
    logger.warning(f"Failed to rebuild ToolContext model: {e}")
