"""내장 slash commands."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
import yaml
from datetime import datetime
from pathlib import Path

from commands import CommandRegistry
from core.project_paths import get_project_paths


def register(
    registry: CommandRegistry,
    get_session=None,
    get_runtime=None,
) -> None:
    """빌트인 명령어 등록."""

    paths = get_project_paths(Path(__file__).resolve().parent.parent)
    project_root = paths.root
    wiki_root = paths.wiki_dir
    raw_root = paths.raw_dir

    @registry.command("help", "Show available commands")
    def cmd_help(args: str = "", **ctx) -> str:
        lines = ["Available commands:", ""]
        for cmd in registry.list_commands():
            lines.append(f"  /{cmd.name:<16} {cmd.description}")
        lines.append("")
        lines.append("Type your message to chat, or /command to run a command.")
        return "\n".join(lines)

    @registry.command("status", "Show session status and token usage")
    def cmd_status(args: str = "", **ctx) -> str:
        session = get_session() if get_session else None
        if not session:
            return "No active session."
        u = session.total_usage
        lines = [
            f"Session: {session.id}",
            f"Messages: {len(session.messages)}",
            f"Tokens: {u.eval_count} generated",
            f"Speed: {u.tok_per_sec:.1f} tok/s" if u.tok_per_sec else "",
        ]
        return "\n".join(l for l in lines if l)

    @registry.command("compact", "Compress old messages to save context (LLM summary)")
    async def cmd_compact(args: str = "", **ctx) -> str:
        session = get_session() if get_session else None
        if not session:
            return "No active session."
        keep = int(args) if args.strip().isdigit() else 20
        runtime = get_runtime() if get_runtime else None
        engine = runtime.engine if runtime else None
        return await session.compact(keep_last=keep, engine=engine)

    @registry.command("sessions", "List saved sessions")
    def cmd_sessions(args: str = "", **ctx) -> str:
        from core.session import Session
        sessions = Session.list_sessions()
        if not sessions:
            return "No saved sessions."
        lines = ["Saved sessions:", ""]
        for s in sessions[:20]:
            modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["modified"]))
            lines.append(f"  {s['id']}  {modified}  ({s['size']}B)")
        return "\n".join(lines)

    @registry.command("resume", "Resume a saved session")
    def cmd_resume(args: str = "", **ctx) -> str:
        if not args.strip():
            return "Usage: /resume <session-id>"
        # 실제 resume은 CLI에서 처리
        return f"__RESUME__:{args.strip()}"

    @registry.command("clear", "Clear current conversation")
    def cmd_clear(args: str = "", **ctx) -> str:
        return "__CLEAR__"

    @registry.command("tools", "List available tools")
    def cmd_tools(args: str = "", **ctx) -> str:
        runtime = get_runtime() if get_runtime else None
        if not runtime:
            return "No runtime available."
        tools = runtime.tools.list_tools()
        lines = [f"Available tools ({len(tools)}):", ""]
        for t in tools:
            lines.append(f"  {t.name:<16} [{t.permission_level.value}]  {t.description[:60]}")
        return "\n".join(lines)

    @registry.command("model", "Show current model info")
    def cmd_model(args: str = "", **ctx) -> str:
        runtime = get_runtime() if get_runtime else None
        if not runtime:
            return "No runtime."
        return f"Model: {runtime.engine.model}"

    @registry.command("config", "Show loaded config (CLAUDE.md, skills, agents)")
    def cmd_config(args: str = "", **ctx) -> str:
        runtime = get_runtime() if get_runtime else None
        if not runtime or not runtime.project_config:
            return "No config loaded."
        cfg = runtime.project_config
        lines = [f"Config dir: {cfg.config_dir}", ""]
        lines.append(f"CLAUDE.md: {'loaded' if cfg.claude_md else 'not found'}")
        if cfg.skills:
            lines.append(f"\nSkills ({len(cfg.skills)}):")
            for s in cfg.skills:
                tools = ", ".join(s.tools) if s.tools else "—"
                lines.append(f"  {s.name:<16} tools=[{tools}]")
        if cfg.agents:
            lines.append(f"\nAgents ({len(cfg.agents)}):")
            for a in cfg.agents:
                tools = ", ".join(a.tools) if a.tools else "—"
                lines.append(f"  {a.name:<16} role={a.role}  tools=[{tools}]")
        return "\n".join(lines)

    @registry.command("query", "Query knowledge base with LLM (usage: /query <question> [--no-save])")
    def cmd_query(args: str = "", **ctx) -> str:
        from skills.memvid_ops import capsule_put, capsule_search

        parts = args.strip().split()
        if not parts:
            return "Usage: /query <question> [--no-save]"

        no_save = "--no-save" in parts
        question = " ".join(p for p in parts if p != "--no-save")
        if not question:
            return "Usage: /query <question> [--no-save]"

        # 1. Hybrid search
        results = capsule_search(question, mode="hybrid", top_k=5)
        if not results:
            return f"No knowledge base results for: {question}"

        # 2. Build context from results
        contexts = []
        for r in results:
            wiki_path = r.get("wiki_path", "")
            if wiki_path:
                full_path = project_root / wiki_path
                if full_path.exists():
                    doc_content = full_path.read_text(encoding="utf-8")
                    contexts.append(f"### {r.get('title', wiki_path)}\n(source: {wiki_path})\n\n{doc_content}")
                    continue
            contexts.append(f"### {r.get('title', 'Untitled')}\n(score: {r.get('score', 0)})\n\n{r.get('snippet', '')}")

        context_text = "\n\n---\n\n".join(contexts)

        # 3. LLM call
        runtime = get_runtime() if get_runtime else None
        if not runtime:
            return f"## Context for: {question}\n\n{context_text}\n\n(No LLM runtime available)"

        import asyncio

        system_msg = "다음 지식 베이스 문서를 참고하여 질문에 답해줘. 출처를 명시해줘."
        user_msg = f"## 참고 문서\n{context_text}\n\n## 질문\n{question}"

        from core.types import Message as Msg, Role
        msgs = [Msg(role=Role.USER, content=user_msg)]
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        runtime.engine.chat(msgs, system=system_msg, temperature=0.5, max_tokens=2048),
                    ).result()
            else:
                result = asyncio.run(
                    runtime.engine.chat(msgs, system=system_msg, temperature=0.5, max_tokens=2048)
                )
            answer = result[0]
        except Exception as e:
            return f"LLM error: {e}\n\n## Context\n{context_text}"

        # 4. Save if not --no-save
        if not no_save:
            today = datetime.now().strftime("%Y-%m-%d")
            slug = re.sub(r'[^a-z0-9]+', '-', question.lower())[:50].strip('-')

            queries_dir = wiki_root / "queries"
            queries_dir.mkdir(parents=True, exist_ok=True)
            query_file = queries_dir / f"{today}-{slug}.md"
            query_content = (
                f"---\ntitle: \"Q: {question}\"\ntype: query\n"
                f"created: {today}\n---\n\n"
                f"## Question\n{question}\n\n"
                f"## Answer\n{answer}\n\n"
                f"## Sources\n" +
                "\n".join(f"- {r.get('title', '')} ({r.get('wiki_path', 'snippet')})" for r in results) +
                "\n"
            )
            query_file.write_text(query_content, encoding="utf-8")

            capsule_put(
                content=query_content,
                title=f"Q: {question}",
                tags=["query-result"],
                wiki_path=f".internal/wiki/queries/{today}-{slug}.md",
            )

            index_path = wiki_root / "index.md"
            if index_path.exists():
                index_text = index_path.read_text(encoding="utf-8")
                new_entry = f"- [Q: {question}](queries/{today}-{slug}.md)"
                if new_entry not in index_text:
                    index_text = index_text.replace(
                        "## Queries\n",
                        f"## Queries\n\n{new_entry}\n",
                    )
                    index_path.write_text(index_text, encoding="utf-8")

            log_path = wiki_root / "log.md"
            if log_path.exists():
                log_text = log_path.read_text(encoding="utf-8")
                log_entry = f"| {today} | query | queries/{today}-{slug}.md | Q: {question} |"
                log_text = log_text.rstrip() + "\n" + log_entry + "\n"
                log_path.write_text(log_text, encoding="utf-8")

        return answer

    @registry.command("wiki-search", "Search knowledge base (usage: /wiki-search <query> [--mode lex|vec|hybrid] [--top-k N])")
    def cmd_wiki_search(args: str = "", **ctx) -> str:
        from skills.memvid_ops import capsule_search

        parts = args.strip().split()
        if not parts:
            return "Usage: /wiki-search <query> [--mode lex|vec|hybrid] [--top-k N]"

        mode = "hybrid"
        top_k = 10
        query_parts = []

        i = 0
        while i < len(parts):
            if parts[i] == "--mode" and i + 1 < len(parts):
                mode = parts[i + 1]
                i += 2
            elif parts[i] == "--top-k" and i + 1 < len(parts):
                try:
                    top_k = int(parts[i + 1])
                except ValueError:
                    pass
                i += 2
            else:
                query_parts.append(parts[i])
                i += 1

        query = " ".join(query_parts)
        if not query:
            return "Usage: /wiki-search <query> [--mode lex|vec|hybrid] [--top-k N]"

        results = capsule_search(query, mode=mode, top_k=top_k)
        if not results:
            return "No results found."

        try:
            from rich.table import Table
            from rich.console import Console
            import io

            table = Table(title=f"Search: {query} (mode={mode})")
            table.add_column("#", style="dim", width=3)
            table.add_column("Score", width=6)
            table.add_column("Title", width=30)
            table.add_column("Path", width=30)
            table.add_column("Snippet", width=50)

            for idx, r in enumerate(results, 1):
                table.add_row(
                    str(idx),
                    f"{r.get('score', 0):.4f}",
                    r.get("title", "")[:30],
                    r.get("wiki_path", "")[:30] or "-",
                    r.get("snippet", "")[:50].replace("\n", " "),
                )

            buf = io.StringIO()
            console = Console(file=buf, width=140)
            console.print(table)
            return buf.getvalue()
        except ImportError:
            pass

        lines = [f"Search: {query} (mode={mode})", ""]
        lines.append(f"{'#':<3} {'Score':<8} {'Title':<30} {'Path':<30} {'Snippet':<50}")
        lines.append("-" * 121)
        for idx, r in enumerate(results, 1):
            lines.append(
                f"{idx:<3} {r.get('score', 0):<8.4f} "
                f"{r.get('title', '')[:30]:<30} "
                f"{(r.get('wiki_path', '') or '-')[:30]:<30} "
                f"{r.get('snippet', '')[:50].replace(chr(10), ' '):<50}"
            )
        return "\n".join(lines)

    @registry.command("wiki-export", "Export wiki (usage: /wiki-export [--format mv2|md-bundle|html])")
    def cmd_wiki_export(args: str = "", **ctx) -> str:
        wiki_dir = wiki_root
        exports_dir = project_root / "exports"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Parse --format
        parts = args.strip().split()
        fmt = "mv2"
        i = 0
        while i < len(parts):
            if parts[i] == "--format" and i + 1 < len(parts):
                fmt = parts[i + 1]
                i += 2
            else:
                i += 1

        if fmt not in ("mv2", "md-bundle", "html"):
            return f"Unknown format: {fmt}. Use mv2, md-bundle, or html."

        if fmt == "mv2":
            out_dir = exports_dir / "mv2" / timestamp
            out_dir.mkdir(parents=True, exist_ok=True)
            copied = []
            for name in ("memory.mv2", "memory.mp4", "memory_index.json", "memory.json"):
                src = wiki_dir / name
                if src.exists():
                    shutil.copy2(src, out_dir / name)
                    copied.append(name)
            if not copied:
                return "No capsule files found to export."
            return f"Exported {len(copied)} file(s) to {out_dir}"

        elif fmt == "md-bundle":
            out_dir = exports_dir / "md-bundle"
            out_dir.mkdir(parents=True, exist_ok=True)
            archive_base = out_dir / timestamp
            shutil.make_archive(str(archive_base), "gztar", root_dir=str(wiki_dir.parent), base_dir=wiki_dir.name)
            return f"Exported to {archive_base}.tar.gz"

        else:  # html
            out_dir = exports_dir / "html" / timestamp
            out_dir.mkdir(parents=True, exist_ok=True)

            # Try markdown library, fallback to <pre>
            try:
                import markdown
                convert = lambda text: markdown.markdown(text)
            except ImportError:
                convert = lambda text: f"<pre>{text}</pre>"

            html_files = []
            for md_file in sorted(wiki_dir.rglob("*.md")):
                rel = md_file.relative_to(wiki_dir)
                content = md_file.read_text(encoding="utf-8")
                html_name = str(rel).replace(".md", ".html")

                html_content = (
                    f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
                    f"<title>{rel.stem}</title></head><body>"
                    f"{convert(content)}</body></html>"
                )
                html_path = out_dir / html_name
                html_path.parent.mkdir(parents=True, exist_ok=True)
                html_path.write_text(html_content, encoding="utf-8")
                html_files.append(html_name)

            # Generate index.html
            links = "\n".join(f'<li><a href="{f}">{f}</a></li>' for f in html_files)
            index_html = (
                f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
                f"<title>Wiki Export</title></head><body>"
                f"<h1>Wiki Export ({timestamp})</h1><ul>{links}</ul></body></html>"
            )
            (out_dir / "index.html").write_text(index_html, encoding="utf-8")
            return f"Exported {len(html_files)} page(s) to {out_dir}"

    @registry.command("exit", "Exit the CLI")
    def cmd_exit(args: str = "", **ctx) -> str:
        return "__EXIT__"

    @registry.command("lint", "Check wiki consistency (usage: /lint [--fix])")
    def cmd_lint(args: str = "", **ctx) -> str:
        wiki_dir = wiki_root
        index_path = wiki_dir / "index.md"
        fix = "--fix" in args

        issues: dict[str, list[str]] = {
            "orphan_docs": [],
            "broken_links": [],
            "capsule_desync": [],
            "frontmatter": [],
        }

        # --- 1. Index consistency ---
        exclude = {"_schema.md", "log.md", "index.md"}
        all_md_files: set[str] = set()
        for md in wiki_dir.rglob("*.md"):
            rel = str(md.relative_to(wiki_dir))
            if rel not in exclude and not rel.startswith("."):
                all_md_files.add(rel)

        # Parse index.md for linked files
        index_text = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
        linked_re = re.compile(r'\[.*?\]\((.+?\.md)\)')
        indexed_files: set[str] = set()
        for m in linked_re.finditer(index_text):
            indexed_files.add(m.group(1))

        orphans = all_md_files - indexed_files
        broken = indexed_files - all_md_files
        for o in sorted(orphans):
            issues["orphan_docs"].append(f"Not in index: {o}")
        for b in sorted(broken):
            issues["broken_links"].append(f"File missing: {b}")

        # --- 2. Capsule sync check ---
        from skills.memvid_ops import _load_stub, _sha256

        entries = _load_stub()
        capsule_hashes = {}
        for e in entries:
            wp = e.get("wiki_path", "")
            if wp:
                capsule_hashes[wp] = e.get("sha256", "")

        for md in wiki_dir.rglob("*.md"):
            rel_from_parent = str(md.relative_to(wiki_dir.parent))
            content = md.read_text(encoding="utf-8")
            file_hash = _sha256(content)
            if rel_from_parent in capsule_hashes:
                if capsule_hashes[rel_from_parent] != file_hash:
                    issues["capsule_desync"].append(f"Hash mismatch: {rel_from_parent}")
            else:
                rel_wiki = str(md.relative_to(wiki_dir))
                if rel_wiki not in exclude:
                    issues["capsule_desync"].append(f"Not in capsule: {rel_from_parent}")

        # --- 3. Frontmatter check ---
        required_fields = {"title", "type", "tags"}
        for md in wiki_dir.rglob("*.md"):
            rel = str(md.relative_to(wiki_dir))
            if rel in exclude or rel.startswith("."):
                continue
            content = md.read_text(encoding="utf-8")
            if not content.startswith("---"):
                issues["frontmatter"].append(f"No frontmatter: {rel}")
                continue
            parts = content.split("---", 2)
            if len(parts) < 3:
                issues["frontmatter"].append(f"Malformed frontmatter: {rel}")
                continue
            try:
                fm = yaml.safe_load(parts[1])
                if not isinstance(fm, dict):
                    issues["frontmatter"].append(f"Invalid YAML: {rel}")
                    continue
                missing = required_fields - set(fm.keys())
                if missing:
                    issues["frontmatter"].append(f"Missing {', '.join(sorted(missing))}: {rel}")
            except yaml.YAMLError:
                issues["frontmatter"].append(f"YAML parse error: {rel}")

        # --- 4. --fix ---
        fixed = []
        if fix:
            # Fix index: add orphans
            if orphans:
                for o in sorted(orphans):
                    title = Path(o).stem.replace("-", " ").title()
                    entry = f"- [{title}]({o})"
                    if entry not in index_text:
                        # Determine section by subdirectory
                        section = "## References"
                        if o.startswith("concepts/"):
                            section = "## Concepts"
                        elif o.startswith("guides/"):
                            section = "## Guides"
                        elif o.startswith("queries/"):
                            section = "## Queries"
                        index_text = index_text.replace(
                            f"{section}\n",
                            f"{section}\n\n{entry}\n",
                        )
                index_path.write_text(index_text, encoding="utf-8")
                fixed.append(f"Added {len(orphans)} orphan(s) to index")

            # Fix broken links: remove from index
            if broken:
                lines = index_text.split("\n")
                new_lines = []
                for line in lines:
                    skip = False
                    for b in broken:
                        if f"]({b})" in line:
                            skip = True
                            break
                    if not skip:
                        new_lines.append(line)
                index_path.write_text("\n".join(new_lines), encoding="utf-8")
                fixed.append(f"Removed {len(broken)} broken link(s) from index")

            # Fix capsule desync
            if issues["capsule_desync"]:
                from skills.memvid_ops import capsule_sync_all
                result = capsule_sync_all(wiki_dir)
                fixed.append(f"Capsule re-synced: {result['synced']} updated, {result['skipped']} unchanged")

        # --- Output ---
        total = sum(len(v) for v in issues.values())
        lines = [f"Wiki Lint {'(with --fix)' if fix else ''}", "---"]

        for category, items in issues.items():
            label = category.replace("_", " ").title()
            if items:
                lines.append(f"\n{label} ({len(items)}):")
                for item in items:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"\n{label}: OK")

        if fix and fixed:
            lines.append(f"\nFixes applied:")
            for f_msg in fixed:
                lines.append(f"  - {f_msg}")

        lines.append(f"\nTotal issues: {total}")
        return "\n".join(lines)

    @registry.command("wiki-status", "Show wiki + capsule dashboard")
    def cmd_wiki_status(args: str = "", **ctx) -> str:
        from skills.memvid_ops import capsule_info, _load_stub, _sha256, STUB_PATH, WIKI_DIR

        wiki_dir = WIKI_DIR
        exclude = {"_schema.md", "log.md", "index.md"}

        # Count documents by type
        type_counts: dict[str, int] = {}
        total_docs = 0
        for md in wiki_dir.rglob("*.md"):
            rel = str(md.relative_to(wiki_dir))
            if rel in exclude or rel.startswith("."):
                continue
            total_docs += 1
            content = md.read_text(encoding="utf-8")
            doc_type = "unknown"
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    try:
                        fm = yaml.safe_load(parts[1])
                        if isinstance(fm, dict):
                            doc_type = fm.get("type", "unknown")
                    except yaml.YAMLError:
                        pass
            type_counts[doc_type] = type_counts.get(doc_type, 0) + 1

        # Raw files (non-.md in .internal/wiki/)
        raw_files = sum(1 for f in wiki_dir.rglob("*") if f.is_file() and f.suffix != ".md")

        # Capsule info
        info = capsule_info()

        # Sync check
        entries = _load_stub()
        capsule_hashes = {e.get("wiki_path", ""): e.get("sha256", "") for e in entries}
        out_of_sync = 0
        for md in wiki_dir.rglob("*.md"):
            rel = str(md.relative_to(wiki_dir))
            if rel in exclude or rel.startswith("."):
                continue
            rel_parent = str(md.relative_to(wiki_dir.parent))
            content = md.read_text(encoding="utf-8")
            file_hash = _sha256(content)
            if rel_parent in capsule_hashes:
                if capsule_hashes[rel_parent] != file_hash:
                    out_of_sync += 1
            else:
                out_of_sync += 1

        # Capsule file info
        capsule_file = ".internal/wiki/memory.json"
        capsule_kb = 0
        capsule_modified = "N/A"
        if STUB_PATH.exists():
            capsule_kb = round(STUB_PATH.stat().st_size / 1024, 1)
            mtime = os.path.getmtime(STUB_PATH)
            capsule_modified = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")

        # Format type breakdown
        type_parts = []
        for t in ["concept", "guide", "reference", "query-result"]:
            c = type_counts.get(t, 0)
            if c:
                type_parts.append(f"{t}s: {c}")
        if type_counts.get("unknown", 0):
            type_parts.append(f"unknown: {type_counts['unknown']}")
        type_str = ", ".join(type_parts) if type_parts else "none"

        sync_str = "All synced" if out_of_sync == 0 else f"{out_of_sync} file(s) out of sync"

        lines = [
            "Wiki Status",
            "---",
            f"Documents:  {total_docs} ({type_str})",
            f"Raw files:  {raw_files}",
            f"Capsule:    {capsule_file} ({capsule_kb} KB, last modified: {capsule_modified})",
            f"Sync:       {sync_str}",
        ]
        return "\n".join(lines)

    @registry.command("wiki-history", "Show topic history (usage: /wiki-history <topic> [--since YYYY-MM-DD])")
    def cmd_wiki_history(args: str = "", **ctx) -> str:
        from skills.memvid_ops import capsule_search

        parts = args.strip().split()
        if not parts:
            return "Usage: /wiki-history <topic> [--since YYYY-MM-DD]"

        since_date = None
        topic_parts = []
        i = 0
        while i < len(parts):
            if parts[i] == "--since" and i + 1 < len(parts):
                since_date = parts[i + 1]
                i += 2
            else:
                topic_parts.append(parts[i])
                i += 1
        topic = " ".join(topic_parts)
        if not topic:
            return "Usage: /wiki-history <topic> [--since YYYY-MM-DD]"

        results = capsule_search(topic, mode="hybrid", top_k=20)
        if not results:
            return f"No history found for: {topic}"

        # Extract timestamps and sort
        enriched = []
        for r in results:
            ts = ""
            for tag in r.get("tags", []):
                if re.match(r'\d{4}-\d{2}-\d{2}', tag):
                    ts = tag
                    break
            # Try extracting created date from snippet frontmatter
            if not ts:
                created_match = re.search(r'created:\s*(\d{4}-\d{2}-\d{2})', r.get("snippet", ""))
                if created_match:
                    ts = created_match.group(1)
            # Fallback: check capsule timestamp
            if not ts:
                ts = "unknown"
            enriched.append({**r, "date": ts})

        # Filter by --since
        if since_date:
            enriched = [e for e in enriched if e["date"] >= since_date or e["date"] == "unknown"]

        # Sort by date
        enriched.sort(key=lambda x: x["date"] if x["date"] != "unknown" else "9999")

        if not enriched:
            return f"No results after {since_date} for: {topic}"

        lines = [f"History for '{topic}'", "---"]
        for e in enriched:
            # Detect type from wiki_path
            doc_type = "doc"
            wp = e.get("wiki_path", "")
            if "concepts/" in wp:
                doc_type = "concept"
            elif "guides/" in wp:
                doc_type = "guide"
            elif "references/" in wp:
                doc_type = "reference"
            elif "queries/" in wp:
                doc_type = "query"

            title = e.get("title", "untitled")[:60]
            snippet = e.get("snippet", "")[:80].replace("\n", " ").strip()
            lines.append(f"{e['date']} | [{doc_type}] {title} | {snippet}")

        return "\n".join(lines)

    @registry.command("ingest", "Ingest raw file into wiki (usage: /ingest <path> [--manual])")
    def cmd_ingest(args: str = "", **ctx) -> str:
        from skills.memvid_ops import capsule_put

        parts = args.strip().split()
        if not parts:
            return "Usage: /ingest <raw_path> [--manual]"

        manual = "--manual" in parts
        raw_path_str = [p for p in parts if p != "--manual"][0] if parts else ""
        if not raw_path_str:
            return "Usage: /ingest <raw_path> [--manual]"

        normalized = raw_path_str.strip()
        raw_candidates = [
            project_root / normalized,
            raw_root / normalized,
        ]
        if normalized.startswith("raw/"):
            raw_candidates.append(raw_root / normalized.removeprefix("raw/"))
        if normalized.startswith(".internal/raw/"):
            raw_candidates.append(project_root / normalized)
        raw_path = next((candidate for candidate in raw_candidates if candidate.exists()), Path(normalized))
        if not raw_path.exists():
            return f"File not found: {raw_path_str}"
        if raw_path.suffix not in (".md", ".txt"):
            return f"Unsupported format: {raw_path.suffix} (only .md, .txt)"

        content = raw_path.read_text(encoding="utf-8")
        today = datetime.now().strftime("%Y-%m-%d")

        # Strip frontmatter to get body text
        body = content
        if content.startswith("---"):
            parts_fm = content.split("---", 2)
            if len(parts_fm) >= 3:
                body = parts_fm[2].strip()

        if manual:
            # Manual mode: minimal metadata, copy as-is
            title = raw_path.stem.replace("-", " ").replace("_", " ").title()
            summary = body[:100].strip()
            tags = ["manual", "reference"]
            key_concepts = []
            # Extract title from frontmatter if present
            if content.startswith("---"):
                for line in content.split("\n")[1:]:
                    if line.strip() == "---":
                        break
                    if line.startswith("title:"):
                        title = line.split(":", 1)[1].strip().strip('"').strip("'")
        else:
            # LLM-assisted summarization
            runtime = get_runtime() if get_runtime else None
            if not runtime:
                return "No runtime available for LLM summarization. Use --manual flag."

            import asyncio

            prompt = (
                "Analyze this document and return ONLY a JSON object:\n"
                '{"title": "...", "summary": "one-line summary", '
                '"key_concepts": ["concept1", "concept2"], '
                '"tags": ["tag1", "tag2"]}\n\n'
                f"Document:\n{content[:2000]}"
            )
            from core.types import Message, Role
            msgs = [Message(role=Role.USER, content=prompt)]
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        result = pool.submit(
                            asyncio.run,
                            runtime.engine.chat(msgs, temperature=0.3, max_tokens=512),
                        ).result()
                else:
                    result = asyncio.run(
                        runtime.engine.chat(msgs, temperature=0.3, max_tokens=512)
                    )
                llm_content = result[0]  # content from (content, thinking, tool_calls, usage)
                # Extract JSON from response
                json_match = re.search(r'\{[^}]+\}', llm_content, re.DOTALL)
                if json_match:
                    import json
                    meta = json.loads(json_match.group())
                    title = meta.get("title", raw_path.stem)
                    summary = meta.get("summary", "")
                    key_concepts = meta.get("key_concepts", [])
                    tags = meta.get("tags", ["reference"])
                else:
                    title = raw_path.stem.replace("-", " ").title()
                    summary = body[:100].strip()
                    key_concepts = []
                    tags = ["reference"]
            except Exception as e:
                title = raw_path.stem.replace("-", " ").title()
                summary = body[:100].strip()
                key_concepts = []
                tags = ["reference", "llm-failed"]

        # Generate slug
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        if not slug:
            slug = raw_path.stem

        # Create .internal/wiki/references/{slug}.md
        references_dir = wiki_root / "references"
        references_dir.mkdir(parents=True, exist_ok=True)
        wiki_file = references_dir / f"{slug}.md"

        tags_yaml = ", ".join(tags)
        concepts_section = ""
        if key_concepts:
            concepts_section = "\n## Key Concepts\n" + "\n".join(f"- {c}" for c in key_concepts) + "\n"

        wiki_content = (
            f"---\n"
            f'title: "{title}"\n'
            f"type: reference\n"
            f"tags: [{tags_yaml}]\n"
            f"created: {today}\n"
            f"updated: {today}\n"
            f"source: {raw_path.name}\n"
            f"---\n\n"
            f"# {title}\n\n"
            f"{summary}\n"
            f"{concepts_section}\n"
            f"---\n\n"
            f"{body}\n"
        )
        wiki_file.write_text(wiki_content, encoding="utf-8")

        # capsule_put
        capsule_put(
            content=wiki_content,
            title=title,
            tags=tags,
            wiki_path=f".internal/wiki/references/{slug}.md",
        )

        # Update .internal/wiki/index.md
        index_path = wiki_root / "index.md"
        index_text = index_path.read_text(encoding="utf-8")
        new_entry = f"- [{title}](references/{slug}.md) -- ingested from {raw_path.name}"
        if new_entry not in index_text:
            index_text = index_text.replace(
                "## References\n",
                f"## References\n\n{new_entry}\n",
            )
            index_path.write_text(index_text, encoding="utf-8")

        # Update .internal/wiki/log.md
        log_path = wiki_root / "log.md"
        log_text = log_path.read_text(encoding="utf-8")
        mode_label = "manual" if manual else "llm"
        log_entry = f"| {today} | ingest ({mode_label}) | references/{slug}.md | {title} |"
        log_text = log_text.rstrip() + "\n" + log_entry + "\n"
        log_path.write_text(log_text, encoding="utf-8")

        return f"Ingested: {raw_path.name} -> .internal/wiki/references/{slug}.md ({len(tags)} tags)"
