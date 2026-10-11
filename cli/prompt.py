"""Interactive yes/no questions."""

from __future__ import annotations


def confirm(question: str, *, default: bool) -> bool:
    """Ask a yes/no question; return the default on Enter or when input runs out."""
    choices = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{question} {choices} ").strip().lower()
    except EOFError:
        print()
        return default
    if not answer:
        return default
    return answer in ("y", "yes")
