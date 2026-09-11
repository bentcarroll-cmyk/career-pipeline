"""Explicit request boundary for packet selections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


class SelectionError(ValueError):
    pass


@dataclass(frozen=True)
class PacketSelection:
    ticket_ids: tuple[str, ...]
    per_role_instructions: Mapping[str, str]


def selection_from_request(
    ticket_ids: Sequence[str],
    per_role_instructions: Mapping[str, str],
    *,
    explicit_request: bool,
) -> PacketSelection:
    if not explicit_request:
        raise SelectionError("packet preparation requires an explicit current request")
    ordered = tuple(dict.fromkeys(ticket.strip() for ticket in ticket_ids if ticket.strip()))
    if not ordered:
        raise SelectionError("at least one exact ticket ID is required")
    unknown = set(per_role_instructions).difference(ordered)
    if unknown:
        raise SelectionError("role instructions reference an unselected ticket")
    return PacketSelection(ordered, dict(per_role_instructions))
