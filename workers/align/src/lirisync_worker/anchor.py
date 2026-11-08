"""The `anchor` method: first-stage placement of lyric lines (`placement`)."""

import itertools
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from lirisync_worker.match_text import Reader
from lirisync_worker.placement import PlacedLine, PlacementOptions, Word, place_lines
from lirisync_worker.protocol import ProtocolError, describe_validation_error
from lirisync_worker.seqalign import AlignmentTooLargeError

if TYPE_CHECKING:
    from lirisync_worker.server import Session

type Milliseconds = Annotated[StrictInt, Field(ge=0)]


class _Word(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start_ms: Milliseconds = Field(alias="startMs")
    end_ms: Milliseconds = Field(alias="endMs")
    text: StrictStr

    @model_validator(mode="after")
    def _ends_after_start(self) -> Self:
        if self.end_ms < self.start_ms:
            raise ValueError("endMs is before startMs")
        return self


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lyrics: list[StrictStr]
    words: list[_Word]
    ignored: list[Annotated[StrictStr, StringConstraints(min_length=1, max_length=1)]]

    @model_validator(mode="after")
    def _ignored_are_unique(self) -> Self:
        if len(set(self.ignored)) != len(self.ignored):
            raise ValueError("ignored has duplicate characters")
        return self

    @model_validator(mode="after")
    def _words_in_time_order(self) -> Self:
        starts = [word.start_ms for word in self.words]
        if any(later < earlier for earlier, later in itertools.pairwise(starts)):
            raise ValueError("words are not in time order")
        return self


def _line(placed: PlacedLine) -> dict[str, object]:
    return {
        "status": placed.status,
        "startMs": placed.start,
        "endMs": placed.end,
        "matchRatio": placed.match_ratio,
        "ambiguous": placed.ambiguous,
    }


def make_anchor(
    reader_factory: Callable[[], Reader],
) -> Callable[["Session", Mapping[str, object]], dict[str, object]]:
    """The handler, creating the reader on first use and keeping it."""
    readers: list[Reader] = []

    def anchor(_session: "Session", params: Mapping[str, object]) -> dict[str, object]:
        try:
            parsed = _Params.model_validate(params)
        except ValidationError as exc:
            problems = describe_validation_error(exc)
            raise ProtocolError(
                "invalid_request", f"anchor params do not match the schema ({problems})"
            ) from None
        if not readers:
            readers.append(reader_factory())
        words = [Word(start=w.start_ms, end=w.end_ms, text=w.text) for w in parsed.words]
        options = PlacementOptions(ignored=frozenset(parsed.ignored))
        try:
            placed = place_lines(parsed.lyrics, words, readers[0], options)
        except AlignmentTooLargeError as exc:
            raise ProtocolError("invalid_request", str(exc)) from None
        return {"lines": [_line(line) for line in placed]}

    return anchor
