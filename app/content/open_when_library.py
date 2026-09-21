"""Loads Open When letters from YAML."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.content.library import ContentError
from app.content.open_when_schema import OpenWhen

logger = logging.getLogger(__name__)


class OpenWhenLibrary:
    """Every enabled Open When letter, ordered for display."""

    def __init__(self, directory: Path, media_dir: Path) -> None:
        self._dir = directory
        self._media_dir = media_dir
        self._by_id: dict[str, OpenWhen] = {}

    def load(self) -> None:
        if not self._dir.exists():
            logger.warning("Open When directory %s does not exist.", self._dir)
            self._by_id = {}
            return

        by_id: dict[str, OpenWhen] = {}

        for path in sorted(self._dir.glob("*.yaml")):
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                raise ContentError(f"{path.name} is not valid YAML:\n{exc}") from exc

            if raw is None:
                continue
            if not isinstance(raw, list):
                raise ContentError(f"{path.name} must contain a YAML list.")

            for entry in raw:
                try:
                    letter = OpenWhen.model_validate(entry)
                except ValidationError as exc:
                    raise ContentError(f"Invalid Open When in {path.name}:\n{exc}") from exc

                if not letter.enabled:
                    continue
                if letter.id in by_id:
                    raise ContentError(f"Duplicate Open When id {letter.id!r}.")
                by_id[letter.id] = letter

        self._by_id = by_id
        logger.info("Loaded %d Open When letters.", len(by_id))

    def get(self, letter_id: str) -> OpenWhen | None:
        return self._by_id.get(letter_id)

    def all(self) -> list[OpenWhen]:
        return sorted(self._by_id.values(), key=lambda l: (l.order, l.title))

    def unlocked(self, today: date, enlistment: date) -> list[OpenWhen]:
        return [l for l in self.all() if l.is_unlocked(today, enlistment)]

    def locked(self, today: date, enlistment: date) -> list[OpenWhen]:
        return [l for l in self.all() if not l.is_unlocked(today, enlistment)]

    def resolve(self, relative: str | None) -> Path | None:
        if not relative:
            return None
        candidate = self._media_dir / relative
        return candidate if candidate.exists() else None

    @property
    def count(self) -> int:
        return len(self._by_id)
