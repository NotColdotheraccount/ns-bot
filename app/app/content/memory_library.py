"""Loads memories from YAML.

Same contract as ContentLibrary: files are the source of truth for what you
wrote, SQLite is the source of truth for what the bot did.

One difference — a memory whose photos are missing is still loaded, because the
text of a memory is worth sending on its own. A voice note with no audio file
is nothing; a memory with no photo is still a memory.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.content.library import ContentError
from app.content.memory_schema import Memory

logger = logging.getLogger(__name__)


class MemoryLibrary:
    """In-memory collection of every enabled Memory."""

    def __init__(self, memories_dir: Path, media_dir: Path) -> None:
        self._dir = memories_dir
        self._media_dir = media_dir
        self._by_id: dict[str, Memory] = {}
        self._by_number: dict[int, Memory] = {}
        self._missing_media: list[str] = []

    def load(self) -> None:
        if not self._dir.exists():
            logger.warning("Memories directory %s does not exist.", self._dir)
            self._by_id, self._by_number = {}, {}
            return

        by_id: dict[str, Memory] = {}
        by_number: dict[int, Memory] = {}
        missing: list[str] = []

        for path in sorted(self._dir.glob("*.yaml")):
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                raise ContentError(f"{path.name} is not valid YAML:\n{exc}") from exc

            if raw is None:
                continue
            if not isinstance(raw, list):
                raise ContentError(f"{path.name} must contain a YAML list of memories.")

            for entry in raw:
                try:
                    memory = Memory.model_validate(entry)
                except ValidationError as exc:
                    raise ContentError(f"Invalid memory in {path.name}:\n{exc}") from exc

                if not memory.enabled:
                    continue
                if memory.id in by_id:
                    raise ContentError(f"Duplicate memory id {memory.id!r} in {path.name}.")
                if memory.number in by_number:
                    raise ContentError(
                        f"Duplicate memory number {memory.number} in {path.name} "
                        f"(already used by {by_number[memory.number].id!r})."
                    )

                for relative in (*memory.photos, *memory.videos):
                    if not (self._media_dir / relative).exists():
                        missing.append(f"{memory.id} -> {relative}")

                by_id[memory.id] = memory
                by_number[memory.number] = memory

        self._by_id, self._by_number, self._missing_media = by_id, by_number, missing

        logger.info("Loaded %d memories.", len(by_id))
        if missing:
            logger.warning("%d memory media file(s) not found.", len(missing))

    # --------------------------------------------------------------- querying

    def get(self, memory_id: str) -> Memory | None:
        return self._by_id.get(memory_id)

    def by_number(self, number: int) -> Memory | None:
        return self._by_number.get(number)

    def existing_files(self, relatives: tuple[str, ...]) -> list[Path]:
        """Absolute paths for the entries that actually exist on disk."""
        paths = []
        for relative in relatives:
            candidate = self._media_dir / relative
            if candidate.exists():
                paths.append(candidate)
        return paths

    def resolve(self, relative: str | None) -> Path | None:
        if not relative:
            return None
        candidate = self._media_dir / relative
        return candidate if candidate.exists() else None

    def select(self, *, tags: tuple[str, ...] = ()) -> list[Memory]:
        return [m for m in self._by_id.values() if m.matches_any_tag(tags)]

    @property
    def memories(self) -> list[Memory]:
        return list(self._by_id.values())

    @property
    def missing_media(self) -> list[str]:
        return list(self._missing_media)

    @property
    def count(self) -> int:
        return len(self._by_id)
