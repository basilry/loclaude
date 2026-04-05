"""URL 내용 가져오기 도구."""

from __future__ import annotations

import httpx

from core.tool_registry import ToolRegistry
from core.types import PermissionMode


def register(registry: ToolRegistry, **_) -> None:

    @registry.tool(
        name="web_fetch",
        description="Fetch a URL and return its text content (HTML stripped to text).",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "max_length": {"type": "integer", "description": "Max chars to return", "default": 8000},
            },
            "required": ["url"],
        },
        permission_level=PermissionMode.FULL_ACCESS,
    )
    async def web_fetch(url: str, max_length: int = 8000) -> dict:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                r = await client.get(url, headers={"User-Agent": "local-claude/0.1"})
                r.raise_for_status()
                text = r.text

                # 간단한 HTML→텍스트 변환
                if "<html" in text.lower() or "<body" in text.lower():
                    text = _strip_html(text)

                if len(text) > max_length:
                    text = text[:max_length] + "\n...(truncated)"

                return {"output": f"[{r.status_code}] {url}\n\n{text}"}
        except Exception as e:
            return {"output": f"Fetch error: {e}"}


def _strip_html(html: str) -> str:
    """최소한의 HTML→텍스트 변환."""
    import re
    # script/style 제거
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # 태그 제거
    text = re.sub(r"<[^>]+>", " ", text)
    # 연속 공백 정리
    text = re.sub(r"\s+", " ", text).strip()
    return text
