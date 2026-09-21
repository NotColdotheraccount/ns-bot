"""Loads authored content from YAML files into memory.

Design rule for this project: **files are the source of truth for content you
wrote; SQLite is the source of truth for what the bot did.** This module owns
the first half.

Content is loaded once at startup and can be reloaded with /reloadcontent
without restarting the bot, so you can add a reassurance message from your
phone during bookout, push, and reload.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.content.schema import ContentItem, ContentKind

logger = logging.getLogger(__name__)


class ContentError(Exception):
    """Raised when authored content is invalid."""


class ContentLibrary:
    """In-memory collection of every enabled ContentItem."""

    def __init__(self, content_dir: Path, media_dir: Path) -> None:
        self._content_dir = content_dir
        self._media_dir = media_dir
        self._items: dict[str, ContentItem] = {}
        self._missing_files: list[str] = []

    # ---------------------------------------------------------------- loading

    def load(self) -> None:
        """Parse every .yaml file in the content directory.

        Raises ContentError on invalid content so problems surface at startup.
        A missing *media file* is only a warning: an item referencing a
        recording you have not made yet should not stop the bot from running.
        """
        if not self._content_dir.exists():
            logger.warning("Content directory %s does not exist.", self._content_dir)
            self._items = {}
            return

        items: dict[str, ContentItem] = {}
        missing: list[str] = []

        for path in sorted(self._content_dir.glob("*.yaml")):
            for raw in self._read_file(path):
                try:
                    item = ContentItem.model_validate(raw)
                except ValidationError as exc:
                    raise ContentError(f"Invalid content in {path.name}:\n{exc}") from exc

                if item.id in items:
                    raise ContentError(
                        f"Duplicate content id {item.id!r} found in {path.name}. "
                        "Every id must be unique across all content files."
                    )

                if not item.enabled:
                    continue

                if item.kind.needs_file and not self._media_path(item).exists():
                    missing.append(f"{item.id} -> {item.file}")
                    continue

                items[item.id] = item

        self._items = items
        self._missing_files = missing

        logger.info("Loaded %d content items.", len(items))
        if missing:
            logger.warning(
                "%d item(s) skipped — media file not found: %s",
                len(missing),
                ", ".join(missing[:5]) + ("..." if len(missing) > 5 else ""),
            )

    def _read_file(self, path: Path) -> list[dict]:
        """Read one YAML file and return its list of raw item dicts."""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ContentError(f"{path.name} is not valid YAML:\n{exc}") from exc

        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ContentError(
                f"{path.name} must contain a YAML list of items (each starting "
                "with '- '), not a single mapping."
            )
        return raw

    def _media_path(self, item: ContentItem) -> Path:
        return self._media_dir / (item.file or "")

    # --------------------------------------------------------------- querying

    def get(self, content_id: str) -> ContentItem | None:
        return self._items.get(content_id)

    def resolve_file(self, item: ContentItem) -> Path | None:
        """Absolute path to the item's media file, if it has one."""
        if not item.file:
            return None
        return self._media_path(item)

    def select(
        self,
        *,
        kinds: tuple[ContentKind, ...] = (),
        tags: tuple[str, ...] = (),
        require_all_tags: bool = False,
    ) -> list[ContentItem]:
        """Filter the library. Empty filters mean 'no restriction'."""
        results = []
        for item in self._items.values():
            if kinds and item.kind not in kinds:
                continue
            if tags:
                if require_all_tags:
                    if not all(item.has_tag(tag) for tag in tags):
                        continue
                elif not item.matches_any_tag(tags):
                    continue
            results.append(item)
        return results

    @property
    def items(self) -> list[ContentItem]:
        return list(self._items.values())

    @property
    def missing_files(self) -> list[str]:
        return list(self._missing_files)

    def stats(self) -> dict[str, int]:
        """Counts per kind, for the admin /content command."""
        counts: dict[str, int] = {}
        for item in self._items.values():
            counts[item.kind.value] = counts.get(item.kind.value, 0) + 1
        return counts
