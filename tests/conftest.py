"""Shared fixtures for Local Daikin tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations) -> None:
    """Enable loading Local Daikin from custom_components."""


@pytest.fixture(autouse=True)
def mock_setup_entry() -> Generator[AsyncMock]:
    """Prevent entity platforms from starting during config flow tests."""
    with patch(
        "custom_components.local_daikin.async_setup_entry",
        new=AsyncMock(return_value=True),
    ) as setup_entry:
        yield setup_entry
