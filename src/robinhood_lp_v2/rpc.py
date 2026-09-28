"""Minimal JSON-RPC client for the probe.

Deliberately thin. The capability differences between the two endpoints
(measured, see docs/chain-knowledge.md) are handled by the caller, not
hidden here:

* the official endpoint serves eth_getLogs across 100,000 blocks but has no
  eth_call state a million blocks back;
* Alchemy Free serves that state but caps a single eth_getLogs at 10 blocks;
* the official endpoint returns blockTimestamp 0x0 on every log, so block time
  must come from eth_getBlockByNumber;
* the official endpoint rejects urllib's default User-Agent with 403, so the
  header is set explicitly.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_USER_AGENT = "robinhood-lp-v2/0.1"

#: The Alchemy key lives in .env. Never log or echo the resolved URL.
_KEY_MARKER = "/v2/alch_"


def redact(url: str) -> str:
    """Strip credentials so a URL is safe to print."""
    if _KEY_MARKER in url:
        head, _, _ = url.partition(_KEY_MARKER)
        return head + _KEY_MARKER + "<redacted>"
    return url


class RpcError(RuntimeError):
    def __init__(self, message: str, url: str = "") -> None:
        super().__init__(message)
        self.url = redact(url) if url else ""


class Rpc:
    def __init__(self, url: str, timeout: float = 30.0) -> None:
        if not url:
            raise RpcError("empty endpoint url")
        self._url = url
        self._timeout = timeout

    @property
    def label(self) -> str:
        return redact(self._url)

    # ANN401: JSON-RPC returns whatever the method returns. The typed helpers
    # below are where narrowing happens; annotating this as object would only
    # move the same casts further down.
    def call(self, method: str, params: list[Any]) -> Any:  # noqa: ANN401
        """Issue one JSON-RPC call. Typed helpers below narrow the result."""
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params,
            }
        ).encode()
        request = urllib.request.Request(
            self._url,
            data=payload,
            headers={
                "content-type": "application/json",
                "user-agent": DEFAULT_USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise RpcError(f"HTTP {exc.code}", self._url) from exc
        except urllib.error.URLError as exc:
            raise RpcError(f"transport failure: {exc.reason}", self._url) from exc
        except json.JSONDecodeError as exc:
            raise RpcError(f"non-JSON response: {exc}", self._url) from exc

        if "error" in body:
            err = body["error"]
            raise RpcError(f"{method}: {err.get('code')} {err.get('message')}", self._url)
        return body.get("result")

    # -- typed helpers ----------------------------------------------------

    def chain_id(self) -> int:
        return int(self.call("eth_chainId", []), 16)

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def get_code(self, address: str, block: str = "latest") -> str:
        result = self.call("eth_getCode", [address, block])
        if not isinstance(result, str):
            raise RpcError(f"eth_getCode returned {type(result).__name__}", self._url)
        return result

    def get_logs(
        self,
        address: str,
        topics: list[Any],
        from_block: str,
        to_block: str,
    ) -> list[dict[str, Any]]:
        result = self.call(
            "eth_getLogs",
            [
                {
                    "address": address,
                    "topics": topics,
                    "fromBlock": from_block,
                    "toBlock": to_block,
                }
            ],
        )
        if not isinstance(result, list):
            raise RpcError(f"eth_getLogs returned {type(result).__name__}", self._url)
        return result


def endpoints() -> list[Rpc]:
    """Build the configured endpoints, official first.

    A missing Alchemy key is not an error: the official endpoint alone is a
    complete path for this round.
    """
    official = os.environ.get("ROBINHOOD_OFFICIAL_RPC_URL", "").strip()
    backup = os.environ.get("ROBINHOOD_MAINNET_RPC_URL", "").strip()
    urls = [u for u in (official, backup) if u]
    if not urls:
        raise RpcError("no endpoint configured; copy .env.example to .env")
    return [Rpc(u) for u in urls]
