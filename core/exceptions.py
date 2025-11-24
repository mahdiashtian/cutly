"""Custom exception classes for the application."""

from __future__ import annotations


class CutlyException(Exception):
    """Base exception for all custom exceptions."""

    def __init__(self, message: str, code: str = "UNKNOWN_ERROR") -> None:
        """Initialize exception with message and error code.
        
        Args:
            message: Human-readable error message.
            code: Machine-readable error code.
        """
        self.message = message
        self.code = code
        super().__init__(self.message)


class DatabaseError(CutlyException):
    """Exception raised for database-related errors."""

    def __init__(self, message: str) -> None:
        """Initialize database error.
        
        Args:
            message: Error description.
        """
        super().__init__(message, "DATABASE_ERROR")


class UserNotFoundError(CutlyException):
    """Exception raised when a user is not found."""

    def __init__(self, user_id: int) -> None:
        """Initialize user not found error.
        
        Args:
            user_id: The user ID that was not found.
        """
        super().__init__(f"User with ID {user_id} not found", "USER_NOT_FOUND")
        self.user_id = user_id


class FileNotFoundError(CutlyException):
    """Exception raised when a file is not found."""

    def __init__(self, code: str) -> None:
        """Initialize file not found error.
        
        Args:
            code: The file code that was not found.
        """
        super().__init__(f"File with code {code} not found", "FILE_NOT_FOUND")
        self.code = code


class ChannelNotFoundError(CutlyException):
    """Exception raised when a channel is not found."""

    def __init__(self, channel_id: str) -> None:
        """Initialize channel not found error.
        
        Args:
            channel_id: The channel ID that was not found.
        """
        super().__init__(f"Channel {channel_id} not found", "CHANNEL_NOT_FOUND")
        self.channel_id = channel_id


class InvalidPasswordError(CutlyException):
    """Exception raised when an invalid password is provided."""

    def __init__(self) -> None:
        """Initialize invalid password error."""
        super().__init__("Invalid password provided", "INVALID_PASSWORD")


class PermissionDeniedError(CutlyException):
    """Exception raised when a user lacks required permissions."""

    def __init__(self, action: str) -> None:
        """Initialize permission denied error.
        
        Args:
            action: The action that was denied.
        """
        super().__init__(f"Permission denied for action: {action}", "PERMISSION_DENIED")
        self.action = action


class BroadcastError(CutlyException):
    """Exception raised during broadcast operations."""

    def __init__(self, message: str, failed_count: int = 0) -> None:
        """Initialize broadcast error.
        
        Args:
            message: Error description.
            failed_count: Number of failed broadcasts.
        """
        super().__init__(message, "BROADCAST_ERROR")
        self.failed_count = failed_count

