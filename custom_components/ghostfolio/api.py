"""API client for Ghostfolio."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class GhostfolioAPIError(Exception):
    """Exception to indicate a general API error."""


class GhostfolioAuthError(Exception):
    """Exception to indicate an authentication error."""


class GhostfolioAPI:
    """API client for Ghostfolio."""

    def __init__(self, base_url: str, access_token: str, verify_ssl: bool = True) -> None:
        """Initialize the API client."""
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.verify_ssl = verify_ssl
        self.auth_token: str | None = None
        self._session: aiohttp.ClientSession | None = None

    async def authenticate(self) -> str | None:
        """Authenticate with Ghostfolio and get auth token."""
        url = f"{self.base_url}/api/v1/auth/anonymous"
        payload = {"accessToken": self.access_token}

        try:
            async with self._get_session().post(url, json=payload) as response:
                if response.status in [200, 201]:
                    data = await response.json()
                    self.auth_token = data.get("authToken")
                    return self.auth_token
                else:
                    _LOGGER.error("Authentication failed with status %s", response.status)
                    response_text = await response.text()
                    _LOGGER.debug("Response: %s", response_text)
                    raise GhostfolioAuthError(f"Authentication failed: {response.status}")
        except aiohttp.ClientError as err:
            _LOGGER.error("HTTP error during authentication: %s", err)
            raise GhostfolioAPIError(f"Connection error: {err}") from err

    async def get_portfolio_performance(self, range_param: str = "max", account_id: str | None = None) -> dict[str, Any]:
        """Get portfolio performance data, optionally filtered by account."""
        params = {"range": range_param}
        if account_id:
            params["accounts"] = account_id

        return await self._make_authenticated_request(
            f"{self.base_url}/api/v2/portfolio/performance",
            params=params
        )

    async def get_accounts(self) -> dict[str, Any]:
        """Get list of all accounts."""
        return await self._make_authenticated_request(
            f"{self.base_url}/api/v1/account"
        )

    async def get_holdings(self, account_id: str | None = None) -> dict[str, Any]:
        """Get holdings, optionally filtered by account."""
        # This endpoint returns the current positions (holdings)
        params = {}
        if account_id:
            params["accounts"] = account_id
            
        return await self._make_authenticated_request(
            f"{self.base_url}/api/v1/portfolio/holdings",
            params=params
        )

    async def get_watchlist(self) -> list[dict[str, Any]]:
        """Get watchlist items."""
        return await self._make_authenticated_request(
            f"{self.base_url}/api/v1/watchlist"
        )

    async def get_market_data(self, data_source: str, symbol: str) -> dict[str, Any]:
        """Get market data (price history and profile) for a specific symbol."""
        # This endpoint provides the 'marketData' list and 'assetProfile'
        return await self._make_authenticated_request(
            f"{self.base_url}/api/v1/market-data/{data_source}/{symbol}"
        )

    async def _make_authenticated_request(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Helper to make authenticated requests with retry logic."""
        if not self.auth_token:
            await self.authenticate()

        headers = {"Authorization": f"Bearer {self.auth_token}"}

        try:
            async with self._get_session().get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 401:
                    _LOGGER.info("Token expired, re-authenticating...")
                    await self.authenticate()
                    headers = {"Authorization": f"Bearer {self.auth_token}"}
                    
                    async with self._get_session().get(url, params=params, headers=headers) as retry_response:
                        if retry_response.status == 200:
                            return await retry_response.json()
                        else:
                            response_text = await retry_response.text()
                            raise GhostfolioAPIError(f"API request failed after re-auth: {retry_response.status}")
                else:
                    response_text = await response.text()
                    _LOGGER.error("Failed to fetch data from %s: %s", url, response_text)
                    raise GhostfolioAPIError(f"API request failed: {response.status}")
        except aiohttp.ClientError as err:
            raise GhostfolioAPIError(f"Connection error: {err}") from err

    def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            connector = None
            if not self.verify_ssl:
                connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
