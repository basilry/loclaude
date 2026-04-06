"""Skills (tools) package — re-export register functions."""

from skills import file_ops, bash_exec, search, web_fetch, git_ops, test_runner, wiki_ops

__all__ = ["file_ops", "bash_exec", "search", "web_fetch", "git_ops", "test_runner", "wiki_ops"]
