"""JSONL 기반 세션 관리. claw-code의 Session 패턴 참고."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from core.types import Message, TokenUsage


@dataclass
class Session:
    """대화 세션 — 메시지 히스토리 + JSONL 영속화."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    messages: list[Message] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    session_dir: Path = field(default_factory=lambda: Path("sessions"))
    title: str | None = None

    def __post_init__(self):
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._file = self.session_dir / f"{self.id}.jsonl"

    # ── 메시지 추가 ──

    def add(self, msg: Message) -> None:
        self.messages.append(msg)
        self._append_jsonl(msg)

    def add_usage(self, usage: TokenUsage) -> None:
        self.total_usage.prompt_tokens += usage.prompt_tokens
        self.total_usage.completion_tokens += usage.completion_tokens
        self.total_usage.total_tokens += usage.total_tokens
        self.total_usage.eval_count += usage.eval_count

    # ── 컨텍스트 관리 ──

    def get_context(self, max_messages: int = 100) -> list[Message]:
        """최근 N개 메시지 반환 (시스템 메시지는 항상 포함)."""
        system_msgs = [m for m in self.messages if m.role.value == "system"]
        other_msgs = [m for m in self.messages if m.role.value != "system"]
        return system_msgs + other_msgs[-max_messages:]

    async def compact(self, keep_last: int = 20, engine=None) -> str:
        """LLM 기반 대화 히스토리 압축.

        engine이 있으면 LLM 요약 사용, 없으면 기존 방식(잘라내기).
        """
        if len(self.messages) <= keep_last + 5:
            return "Not enough messages to compact."

        # 시스템 메시지 보존
        system_msgs = [m for m in self.messages if m.role.value == "system"]
        other_msgs = [m for m in self.messages if m.role.value != "system"]

        old_msgs = other_msgs[:-keep_last]
        recent_msgs = other_msgs[-keep_last:]

        from core.types import Role

        if engine:
            summary_prompt = (
                "다음 대화 히스토리를 간결하게 요약해줘. 반드시 포함할 것:\n"
                "1. 핵심 결정사항\n"
                "2. 생성/수정된 파일\n"
                "3. 미해결 작업\n"
                "4. 중요 컨텍스트\n"
                "형식: 마크다운, 200줄 이내\n\n"
                + "\n".join(f"[{m.role.value}] {m.content[:200]}" for m in old_msgs)
            )
            summary, usage = await engine.chat(
                [Message(role=Role.USER, content=summary_prompt)],
                max_tokens=1024,
            )
            summary_msg = Message(
                role=Role.SYSTEM,
                content=f"[이전 대화 요약]\n{summary}",
            )
        else:
            summary_parts = []
            for m in old_msgs:
                preview = m.content[:100] + "..." if len(m.content) > 100 else m.content
                summary_parts.append(f"[{m.role.value}] {preview}")

            summary_text = (
                f"[Compacted {len(old_msgs)} messages]\n"
                + "\n".join(summary_parts[-10:])
            )
            summary_msg = Message(
                role=Role.SYSTEM,
                content=f"Previous conversation summary:\n{summary_text}",
            )

        self.messages = system_msgs + [summary_msg] + recent_msgs
        mode = "LLM summary" if engine else "truncation"
        return f"Compacted {len(old_msgs)} messages → {len(self.messages)} remaining ({mode})."

    # ── 세션 저장/로드 ──

    def _append_jsonl(self, msg: Message) -> None:
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg.to_jsonl(), ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, session_id: str, session_dir: Path | str = "sessions") -> Session:
        """JSONL 파일에서 세션 복원."""
        session_dir = Path(session_dir)
        fpath = session_dir / f"{session_id}.jsonl"
        if not fpath.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")

        session = cls(id=session_id, session_dir=session_dir)
        with open(fpath, encoding="utf-8") as f:
            for line in f:
                data = json.loads(line.strip())
                msg = Message(
                    id=data.get("id", ""),
                    role=data["role"],
                    content=data["content"],
                    thinking=data.get("thinking"),
                    timestamp=data.get("timestamp", 0),
                    name=data.get("name"),
                    tool_call_id=data.get("tool_call_id"),
                )
                session.messages.append(msg)
        return session

    @classmethod
    def list_sessions(cls, session_dir: Path | str = "sessions") -> list[dict]:
        """저장된 세션 목록."""
        session_dir = Path(session_dir)
        if not session_dir.exists():
            return []
        sessions = []
        for f in sorted(session_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            sessions.append({
                "id": f.stem,
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime,
            })
        return sessions


async def auto_title(session: Session, engine) -> None:
    """첫 사용자 메시지로 5단어 이내 세션 제목 자동 생성."""
    if session.title or len(session.messages) < 2:
        return
    first_user = next(
        (m for m in session.messages if m.role.value == "user"), None,
    )
    if not first_user:
        return
    from core.types import Role
    title, usage = await engine.chat(
        [Message(
            role=Role.USER,
            content=(
                f"다음 질문에 대한 5단어 이내 세션 제목을 만들어줘. "
                f"제목만 출력해:\n{first_user.content[:200]}"
            ),
        )],
        max_tokens=20,
    )
    session.title = title.strip().strip('"')
