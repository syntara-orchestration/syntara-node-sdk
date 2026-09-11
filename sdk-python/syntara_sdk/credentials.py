"""Credential handling for Syntara nodes."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CredentialMountType(StrEnum):
    """How credentials are mounted into the execution environment."""

    ENV = "env"  # Environment variable
    FILE = "file"  # File on disk
    TMPFS_FILE = "tmpfs_file"  # RAM-backed tmpfs file
    HEADER = "header"  # HTTP header (for API nodes)


class CredentialReference(BaseModel):
    """Reference to a platform-managed credential.

    Stores only the UUID reference - the platform resolves and injects
    the actual credential value at runtime.
    """

    credential_id: str = Field(..., description="UUID of the credential in the vault")
    credential_mount_type: CredentialMountType = Field(
        default=CredentialMountType.ENV,
        description="How the credential is injected",
    )
    credential_mount_path: str | None = Field(
        default=None,
        description="Path for file/tmpfs_file mounts",
    )
    credential_header_name: str | None = Field(
        default=None,
        description="Header name for header mount type",
    )


class BaseCredential(ABC):
    """Abstract base for credential extraction.

    Subclasses implement specific credential types (API keys, tokens, etc.)
    and know how to extract them from the mounted location.
    """

    def __init__(self, mount_type: CredentialMountType, mount_location: str) -> None:
        """Initialize credential extractor.

        Args:
            mount_type: How the credential is mounted
            mount_location: Where the credential is located
                           (env var name, file path, or header name)
        """
        self.mount_type = mount_type
        self.mount_location = mount_location

    @abstractmethod
    def get_value(self) -> str:
        """Extract and return the credential value.

        Returns:
            The credential value as a string

        Raises:
            ValueError: If the credential cannot be extracted
        """
        pass

    def _read_from_env(self) -> str:
        """Read credential from environment variable.

        Returns:
            Environment variable value

        Raises:
            ValueError: If environment variable is not set
        """
        value = os.getenv(self.mount_location)
        if value is None:
            raise ValueError(
                f"Environment variable '{self.mount_location}' not set"
            )
        return value.strip()

    def _read_from_file(self) -> str:
        """Read credential from file.

        Returns:
            File contents

        Raises:
            ValueError: If file doesn't exist or can't be read
        """
        path = Path(self.mount_location)
        if not path.exists():
            raise ValueError(f"Credential file not found: {path}")
        try:
            return path.read_text().strip()
        except Exception as e:
            raise ValueError(f"Failed to read credential file {path}: {e}")


class ApiKeyCredential(BaseCredential):
    """API key credential.

    Supports both environment variable and file-based mounting.
    """

    def get_value(self) -> str:
        """Extract API key value.

        Returns:
            API key string

        Raises:
            ValueError: If credential cannot be extracted
        """
        if self.mount_type == CredentialMountType.ENV:
            return self._read_from_env()
        elif self.mount_type in (CredentialMountType.FILE, CredentialMountType.TMPFS_FILE):
            return self._read_from_file()
        else:
            raise ValueError(
                f"Unsupported mount type for API key: {self.mount_type}"
            )

    def as_header(self, header_name: str = "X-API-Key") -> dict[str, str]:
        """Format as HTTP header.

        Args:
            header_name: Header name (default: X-API-Key)

        Returns:
            Dictionary with header name and value
        """
        return {header_name: self.get_value()}


class BearerTokenCredential(BaseCredential):
    """Bearer token credential for OAuth/JWT authentication.

    Automatically formats as 'Bearer {token}' for Authorization headers.
    """

    def get_value(self) -> str:
        """Extract bearer token value.

        Returns:
            Token string (without 'Bearer' prefix)

        Raises:
            ValueError: If credential cannot be extracted
        """
        if self.mount_type == CredentialMountType.ENV:
            token = self._read_from_env()
        elif self.mount_type in (CredentialMountType.FILE, CredentialMountType.TMPFS_FILE):
            token = self._read_from_file()
        else:
            raise ValueError(
                f"Unsupported mount type for bearer token: {self.mount_type}"
            )

        # Strip 'Bearer ' prefix if present
        if token.startswith("Bearer "):
            token = token[7:]

        return token

    def as_authorization_header(self) -> dict[str, str]:
        """Format as Authorization header.

        Returns:
            Dictionary with 'Authorization': 'Bearer {token}'
        """
        return {"Authorization": f"Bearer {self.get_value()}"}


class BasicAuthCredential(BaseCredential):
    """Basic authentication credential.

    Expects username:password format in the mounted location.
    """

    def get_value(self) -> str:
        """Extract basic auth credentials.

        Returns:
            'username:password' string

        Raises:
            ValueError: If credential cannot be extracted or is malformed
        """
        if self.mount_type == CredentialMountType.ENV:
            value = self._read_from_env()
        elif self.mount_type in (CredentialMountType.FILE, CredentialMountType.TMPFS_FILE):
            value = self._read_from_file()
        else:
            raise ValueError(
                f"Unsupported mount type for basic auth: {self.mount_type}"
            )

        # Validate format
        if ":" not in value:
            raise ValueError(
                "Basic auth credential must be in 'username:password' format"
            )

        return value

    def as_authorization_header(self) -> dict[str, str]:
        """Format as Authorization header with base64 encoding.

        Returns:
            Dictionary with 'Authorization': 'Basic {base64}'
        """
        import base64

        value = self.get_value()
        encoded = base64.b64encode(value.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    def get_username_password(self) -> tuple[str, str]:
        """Split into username and password.

        Returns:
            Tuple of (username, password)
        """
        value = self.get_value()
        username, password = value.split(":", 1)
        return username, password
