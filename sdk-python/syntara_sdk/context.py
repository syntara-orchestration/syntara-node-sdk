"""Execution context for Syntara nodes."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4


class ExecutionContext:
    """Execution context providing node runtime environment.

    Tracks execution metadata, provides structured logging, and manages
    access to mounted secrets in the tmpfs filesystem.

    Attributes:
        execution_id: Unique identifier for this execution
        workflow_id: Parent workflow identifier
        node_name: Name of the executing node
        secret_mount_path: Base path where secrets are mounted (tmpfs)
        logger: Structured logger for this execution
    """

    def __init__(
        self,
        execution_id: str | UUID | None = None,
        workflow_id: str | UUID | None = None,
        node_name: str = "unknown",
        secret_mount_path: Path | str = "/run/secrets",
    ) -> None:
        """Initialize execution context.

        Args:
            execution_id: Unique execution identifier (generated if not provided)
            workflow_id: Parent workflow identifier
            node_name: Name of the executing node
            secret_mount_path: Base directory for mounted secrets
        """
        self.execution_id = str(execution_id) if execution_id else str(uuid4())
        self.workflow_id = str(workflow_id) if workflow_id else None
        self.node_name = node_name
        self.secret_mount_path = Path(secret_mount_path)

        # Configure structured logger
        self.logger = logging.getLogger(f"syntara.{node_name}")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                json.dumps({
                    "timestamp": "%(asctime)s",
                    "level": "%(levelname)s",
                    "execution_id": self.execution_id,
                    "node": self.node_name,
                    "message": "%(message)s",
                })
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def get_secret_file(self, secret_name: str) -> Path:
        """Get path to a mounted secret file.

        Args:
            secret_name: Name of the secret file

        Returns:
            Path to the secret file in tmpfs

        Raises:
            FileNotFoundError: If the secret file doesn't exist
        """
        secret_path = self.secret_mount_path / secret_name
        if not secret_path.exists():
            raise FileNotFoundError(
                f"Secret file not found: {secret_path}. "
                f"Ensure the credential is mounted at runtime."
            )
        return secret_path

    def read_secret(self, secret_name: str) -> str:
        """Read a mounted secret file and return its contents.

        Args:
            secret_name: Name of the secret file

        Returns:
            Contents of the secret file

        Raises:
            FileNotFoundError: If the secret file doesn't exist
        """
        secret_path = self.get_secret_file(secret_name)
        return secret_path.read_text().strip()

    def log_execution_start(self, inputs: dict[str, Any]) -> None:
        """Log execution start with sanitized inputs.

        Args:
            inputs: Node input parameters (credentials are redacted)
        """
        sanitized = self._sanitize_inputs(inputs)
        self.logger.info(f"Execution started: {sanitized}")

    def log_execution_complete(self, status_code: int, message: str) -> None:
        """Log execution completion.

        Args:
            status_code: Execution status code (0 = success)
            message: Status message
        """
        self.logger.info(
            f"Execution completed: status_code={status_code}, message={message}"
        )

    def log_execution_error(self, error: Exception) -> None:
        """Log execution error.

        Args:
            error: Exception that occurred
        """
        self.logger.error(f"Execution failed: {type(error).__name__}: {error}")

    def _sanitize_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Sanitize inputs by redacting credential values.

        Args:
            inputs: Raw input parameters

        Returns:
            Sanitized inputs with credentials redacted
        """
        sanitized = inputs.copy()
        # Redact common credential field names
        for key in ["password", "token", "api_key", "secret", "credential"]:
            if key in sanitized:
                sanitized[key] = "***REDACTED***"
        return sanitized
