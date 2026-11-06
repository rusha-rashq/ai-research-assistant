"""Verify the network guard really covers both arXiv (httpx) and Anthropic (httpx2)."""
import anthropic
import httpx
import httpx2
import pytest

from conftest import NetworkBlocked


def test_guard_blocks_httpx():
    with pytest.raises(NetworkBlocked):
        httpx.get("https://export.arxiv.org/api/query")


def test_guard_blocks_httpx2():
    with pytest.raises(NetworkBlocked):
        httpx2.get("https://api.anthropic.com")


def test_guard_blocks_real_anthropic_client(api_key):
    client = anthropic.Anthropic()
    with pytest.raises(NetworkBlocked):
        client.messages.create(model="claude-sonnet-5-5", max_tokens=5,
                               messages=[{"role": "user", "content": "hi"}])


def test_anthropic_sdk_uses_httpx2():
    # If this ever flips to httpx, the guard in conftest needs revisiting.
    import anthropic._client as c
    assert c.httpx2 is httpx2
