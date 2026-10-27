"""Tests for HDB Property Information catalogue flat-type helpers."""

from __future__ import annotations

import types

import pytest

from hdb_property_flat_types import SOLD_COLUMN_TO_FLAT_TYPE, flat_types_from_property_row


def test_sold_columns_cover_expected_flat_types():
    labels = [ft for _, ft in SOLD_COLUMN_TO_FLAT_TYPE]
    assert labels == [
        "1 ROOM",
        "2 ROOM",
        "3 ROOM",
        "4 ROOM",
        "5 ROOM",
        "EXECUTIVE",
        "MULTI-GENERATION",
        "STUDIO APARTMENT",
    ]


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (
            {
                "room_3_sold": 26,
                "room_4_sold": 10,
            },
            [("3 ROOM", 26), ("4 ROOM", 10)],
        ),
        (
            {"room_1_sold": 0, "exec_sold": 2},
            [("EXECUTIVE", 2)],
        ),
        (
            {},
            [],
        ),
    ],
)
def test_flat_types_from_property_row(kwargs: dict[str, int], expected: list[tuple[str, int]]):
    base = {
        "room_1_sold": 0,
        "room_2_sold": 0,
        "room_3_sold": 0,
        "room_4_sold": 0,
        "room_5_sold": 0,
        "exec_sold": 0,
        "multigen_sold": 0,
        "studio_apartment_sold": 0,
    }
    base.update(kwargs)
    row = types.SimpleNamespace(**base)
    assert flat_types_from_property_row(row) == expected


def test_flat_types_preserves_catalogue_order_when_many_types():
    row = types.SimpleNamespace(
        room_5_sold=1,
        room_2_sold=2,
        room_3_sold=3,
    )
    assert flat_types_from_property_row(row) == [
        ("2 ROOM", 2),
        ("3 ROOM", 3),
        ("5 ROOM", 1),
    ]
