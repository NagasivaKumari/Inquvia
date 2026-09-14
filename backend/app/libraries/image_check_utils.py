"""Shared helpers for image evidence checks."""
from __future__ import annotations

from ..libraries import signals as signals_lib


def image_inputs(inv: dict) -> list[dict]:
    return [i for i in (inv.get("inputs") or []) if i.get("type") == "image"]


def load_input_bytes(inp: dict) -> bytes | None:
    path = inp.get("filePath")
    if not path:
        return None
    return signals_lib.load_bytes(path)


def input_label(inp: dict, fallback: str = "image") -> str:
    return inp.get("content") or inp.get("fileName") or fallback
