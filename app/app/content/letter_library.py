"""Loads letters from YAML."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.content.letter_schema import Letter
from app.content.library import ContentError

logger = logging.getLogger(__name__)


class LetterLibrary:
    """Every enabled letter, indexed by id and number."""

    def __init__(self, letters_dir: Path, media_dir: Path) -> None:
        self._dir = letters_dir
        self._media_dir = media_dir
        self._by_id: dict[str, Letter] = {}
        self._by_number: dict[int, Letter] = {}

    def load(self) -> None:
        if not self._dir.exists():
            logger.warning("Letters directory %s does not exist.", self._dir)
            self._by_id, self._by_number = {}, {}
            return

        by_id: dict[str, Letter] = {}
        by_number: dict[int, Letter] = {}

        for path in sorted(self._dir.glob("*.yaml")):
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                raise ContentError(f"{path.name} is not valid YAML:\n{exc}") from exc

            if raw is None:
                continue
            if not isinstance(raw, list):
                raise ContentError(f"{path.name} must contain a YAML list of letters.")

            for entry in raw:
                try:
                    letter = Letter.model_validate(entry)
                except ValidationError as exc:
                    raise ContentError(f"Invalid letter in {path.name}:\n{exc}") from exc

                if not letter.enabled:
                    continue
                if letter.id in by_id:
                    raise ContentError(f"Duplicate letter id {letter.id!r} in {path.name}.")
                if letter.number in by_number:
                    raise ContentError(
                        f"Duplicate letter number {letter.number} in {path.name}."
                    )
                by_id[letter.id] = letter
                by_number[letter.number] = letter

        self._by_id, self._by_number = by_id, by_number
        logger.info("Loaded %d letters.", len(by_id))

    def get(self, letter_id: str) -> Letter | None:
        return self._by_id.get(letter_id)

    def by_number(self, number: int) -> Letter | None:
        return self._by_number.get(number)

    def due(self, today: date, enlistment: date) -> list[Letter]:
        """Letters whose date has arrived, oldest first."""
        return sorted(
            (l for l in self._by_id.values() if l.is_due(today, enlistment)),
            key=lambda l: (l.due_on(enlistment), l.number),
        )

    def upcoming(self, today: date, enlistment: date, limit: int = 5) -> list[Letter]:
        return sorted(
            (l for l in self._by_id.values() if not l.is_due(today, enlistment)),
            key=lambda l: (l.due_on(enlistment), l.number),
        )[:limit]

    def resolve(self, relative: str | None) -> Path | None:
        if not relative:
            return None
        candidate = self._media_dir / relative
        return candidate if candidate.exists() else None

    @property
    def letters(self) -> list[Letter]:
        return list(self._by_id.values())

    @property
    def count(self) -> int:
        return len(self._by_id)
