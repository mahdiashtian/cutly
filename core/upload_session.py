"""Upload session management for multi-file uploads.

Handles collecting multiple files from users before generating
a single share link for all uploaded files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

LOGGER = logging.getLogger(__name__)


@dataclass
class UploadedFile:
    """Represents a single uploaded file in a session.
    
    Attributes:
        message_id: Message ID in storage channel (for backup).
        media_type: Type of media (photo, video, document, etc.).
        size: File size in bytes.
        file_id: Telegram file ID for direct access.
        access_hash: Telegram access hash.
        file_reference: Telegram file reference bytes.
        file_name: Optional file name.
    """
    
    message_id: int
    media_type: str
    size: int
    file_id: int
    access_hash: int
    file_reference: bytes
    file_name: Optional[str] = None


@dataclass
class UploadSession:
    """Manages an upload session for a user.
    
    Tracks multiple files uploaded by a user before finalizing
    with a single share code.
    
    Attributes:
        user_id: Telegram user ID.
        files: List of uploaded files in this session.
        total_size: Total size of all files in bytes.
    """
    
    user_id: int
    files: List[UploadedFile] = field(default_factory=list)
    total_size: int = 0
    
    def add_file(
        self,
        message_id: int,
        media_type: str,
        size: int,
        file_id: int,
        access_hash: int,
        file_reference: bytes,
        file_name: Optional[str] = None
    ) -> None:
        """Add a file to the session.
        
        Args:
            message_id: Message ID in storage channel (backup).
            media_type: Type of media.
            size: File size in bytes.
            file_id: Telegram file ID.
            access_hash: Telegram access hash.
            file_reference: Telegram file reference bytes.
            file_name: Optional file name.
        """
        self.files.append(UploadedFile(
            message_id=message_id,
            media_type=media_type,
            size=size,
            file_id=file_id,
            access_hash=access_hash,
            file_reference=file_reference,
            file_name=file_name
        ))
        self.total_size += size
        LOGGER.info(f"Added file to session for user {self.user_id}: {media_type} ({size} bytes, file_id={file_id})")
    
    def get_summary(self) -> Dict[str, any]:
        """Get summary statistics of uploaded files.
        
        Returns:
            Dictionary with counts per media type and formatted size.
            
        Examples:
            >>> session.get_summary()
            {'photos': 5, 'videos': 2, 'documents': 1, 'voices': 0, 
             'total_count': 8, 'total_size_mb': 15.0}
        """
        # Count by media type
        photos = sum(1 for f in self.files if f.media_type == 'photo')
        videos = sum(1 for f in self.files if f.media_type == 'video')
        voices = sum(1 for f in self.files if f.media_type == 'voice')
        documents = sum(1 for f in self.files if f.media_type == 'document')
        
        # Convert size to MB
        total_size_mb = round(self.total_size / (1024 * 1024), 2)
        
        return {
            'photos': photos,
            'videos': videos,
            'voices': voices,
            'documents': documents,
            'total_count': len(self.files),
            'total_size_mb': total_size_mb,
        }
    
    def clear(self) -> None:
        """Clear all files from the session."""
        self.files.clear()
        self.total_size = 0
        LOGGER.info(f"Cleared session for user {self.user_id}")
    
    def is_empty(self) -> bool:
        """Check if session has no files.
        
        Returns:
            True if no files uploaded yet.
        """
        return len(self.files) == 0


class UploadSessionManager:
    """Manages upload sessions for all users.
    
    Provides a singleton interface to track and manage
    multi-file upload sessions across all bot users.
    
    Examples:
        >>> manager = UploadSessionManager()
        >>> manager.start_session(12345678)
        >>> manager.add_file(12345678, message_id=100, media_type="photo", size=50000)
        >>> summary = manager.get_session(12345678).get_summary()
        >>> manager.end_session(12345678)
    """
    
    def __init__(self) -> None:
        """Initialize the session manager."""
        self._sessions: Dict[int, UploadSession] = {}
    
    def start_session(self, user_id: int) -> UploadSession:
        """Start a new upload session for a user.
        
        If a session already exists, it will be cleared and reused.
        
        Args:
            user_id: Telegram user ID.
            
        Returns:
            The upload session.
        """
        if user_id in self._sessions:
            self._sessions[user_id].clear()
        else:
            self._sessions[user_id] = UploadSession(user_id=user_id)
        
        LOGGER.info(f"Started upload session for user {user_id}")
        return self._sessions[user_id]
    
    def get_session(self, user_id: int) -> Optional[UploadSession]:
        """Get the current upload session for a user.
        
        Args:
            user_id: Telegram user ID.
            
        Returns:
            The upload session, or None if no active session.
        """
        return self._sessions.get(user_id)
    
    def has_session(self, user_id: int) -> bool:
        """Check if user has an active upload session.
        
        Args:
            user_id: Telegram user ID.
            
        Returns:
            True if user has an active session.
        """
        return user_id in self._sessions and not self._sessions[user_id].is_empty()
    
    def add_file(
        self,
        user_id: int,
        message_id: int,
        media_type: str,
        size: int,
        file_name: Optional[str] = None
    ) -> None:
        """Add a file to user's session.
        
        Args:
            user_id: Telegram user ID.
            message_id: Message ID in storage channel.
            media_type: Type of media.
            size: File size in bytes.
            file_name: Optional file name.
            
        Raises:
            ValueError: If user has no active session.
        """
        session = self.get_session(user_id)
        if not session:
            raise ValueError(f"No active upload session for user {user_id}")
        
        session.add_file(message_id, media_type, size, file_name)
    
    def end_session(self, user_id: int) -> None:
        """End and remove user's upload session.
        
        Args:
            user_id: Telegram user ID.
        """
        if user_id in self._sessions:
            del self._sessions[user_id]
            LOGGER.info(f"Ended upload session for user {user_id}")
    
    def clear_session(self, user_id: int) -> None:
        """Alias for end_session. End and remove user's upload session.
        
        Args:
            user_id: Telegram user ID.
        """
        self.end_session(user_id)
    
    def cancel_session(self, user_id: int) -> List[int]:
        """Cancel user's session and return message IDs for deletion.
        
        Args:
            user_id: Telegram user ID.
            
        Returns:
            List of message IDs in storage channel to delete.
        """
        session = self.get_session(user_id)
        if not session:
            return []
        
        message_ids = [f.message_id for f in session.files]
        self.end_session(user_id)
        
        LOGGER.info(f"Cancelled upload session for user {user_id}, {len(message_ids)} files to clean")
        return message_ids


# Global singleton instance
_session_manager: Optional[UploadSessionManager] = None


def get_upload_manager() -> UploadSessionManager:
    """Get the global upload session manager instance.
    
    Returns:
        The singleton UploadSessionManager instance.
    """
    global _session_manager
    if _session_manager is None:
        _session_manager = UploadSessionManager()
    return _session_manager

