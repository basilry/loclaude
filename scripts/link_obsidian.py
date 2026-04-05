"""Obsidian vault symlink script. Links wiki/ into an Obsidian vault."""

import os
import sys
from pathlib import Path


def main():
    project_root = Path(__file__).resolve().parent.parent
    wiki_dir = project_root / "wiki"

    # 1. Detect vault path
    vault_path = None

    # Check env override
    if os.environ.get("OBSIDIAN_VAULT"):
        vault_path = Path(os.environ["OBSIDIAN_VAULT"])
    else:
        # macOS default
        default = Path.home() / "Documents" / "Obsidian Vault"
        if default.exists():
            vault_path = default

    if not vault_path or not vault_path.exists():
        print(f"Obsidian vault not found.")
        print(f"Set OBSIDIAN_VAULT env var or ensure ~/Documents/Obsidian Vault exists.")
        sys.exit(1)

    # 2. Create symlink target
    link_parent = vault_path / "Projects"
    link_parent.mkdir(parents=True, exist_ok=True)
    link_path = link_parent / "local-claude-wiki"

    # 3. Check existing
    if link_path.exists() or link_path.is_symlink():
        if link_path.is_symlink() and link_path.resolve() == wiki_dir.resolve():
            print(f"Symlink already exists and points to correct target.")
            print(f"  {link_path} -> {wiki_dir}")
            return

        print(f"WARNING: {link_path} already exists.")
        answer = input("Overwrite? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)
        if link_path.is_symlink() or link_path.is_file():
            link_path.unlink()
        else:
            import shutil
            shutil.rmtree(link_path)

    # 4. Create symlink
    link_path.symlink_to(wiki_dir)
    print(f"Symlink created:")
    print(f"  {link_path} -> {wiki_dir}")

    # 5. Ensure .gitignore has symlink note
    gitignore = project_root / ".gitignore"
    marker = "# Obsidian symlink"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if marker not in content:
            content = content.rstrip() + f"\n\n{marker}\n# (symlink is external, nothing to ignore)\n"
            gitignore.write_text(content, encoding="utf-8")
    else:
        gitignore.write_text(f"{marker}\n# (symlink is external, nothing to ignore)\n", encoding="utf-8")

    print(f"\nObsidian vault: {vault_path}")
    print(f"Wiki is now browsable in Obsidian under Projects/local-claude-wiki/")


if __name__ == "__main__":
    main()
