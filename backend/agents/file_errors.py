"""File processing error classes.

This module defines exception classes for file processing errors
in the multimodal file upload feature.
"""


class FileProcessingError(Exception):
    """Base exception for file processing errors."""
    
    def __init__(self, message: str, filename: str, retryable: bool = False):
        """Initialize FileProcessingError.
        
        Args:
            message: Error message
            filename: Name of the file that caused the error
            retryable: Whether the error is retryable
        """
        self.message = message
        self.filename = filename
        self.retryable = retryable
        super().__init__(message)


class FileSizeError(FileProcessingError):
    """File size exceeds limit."""
    
    def __init__(self, message: str, filename: str, size: int, max_size: int):
        """Initialize FileSizeError.
        
        Args:
            message: Error message
            filename: Name of the file
            size: Actual file size in bytes
            max_size: Maximum allowed size in bytes
        """
        super().__init__(message, filename, retryable=False)
        self.size = size
        self.max_size = max_size


class FileTypeError(FileProcessingError):
    """Unsupported file type."""
    
    def __init__(self, message: str, filename: str, mime_type: str):
        """Initialize FileTypeError.
        
        Args:
            message: Error message
            filename: Name of the file
            mime_type: MIME type of the file
        """
        super().__init__(message, filename, retryable=False)
        self.mime_type = mime_type


class FileDownloadError(FileProcessingError):
    """Failed to download file from OSS."""
    
    def __init__(self, message: str, filename: str, url: str):
        """Initialize FileDownloadError.
        
        Args:
            message: Error message
            filename: Name of the file
            url: URL of the file
        """
        super().__init__(message, filename, retryable=True)
        self.url = url


class FileParsingError(FileProcessingError):
    """Failed to parse file content."""
    
    def __init__(self, message: str, filename: str, file_type: str):
        """Initialize FileParsingError.
        
        Args:
            message: Error message
            filename: Name of the file
            file_type: Type of file (e.g., 'PDF', 'DOCX', 'image')
        """
        super().__init__(message, filename, retryable=False)
        self.file_type = file_type
