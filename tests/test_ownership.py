from __future__ import annotations

import unittest

from runplan.domain.ownership import (
    OwnershipMetadata,
    OwnershipMetadataError,
    description_with_ownership,
    parse_ownership,
    strip_ownership,
)


class OwnershipMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.metadata = OwnershipMetadata(
            owner_id="test-owner",
            program_id="hca-2026",
            week=31,
            workout_id="long-run",
            date="2026-08-02",
            content_hash="a" * 64,
        )

    def test_round_trip_preserves_readable_description(self) -> None:
        description = description_with_ownership("Easy and controlled.", self.metadata)

        self.assertEqual(self.metadata, parse_ownership(description))
        self.assertEqual(("Easy and controlled.", True), strip_ownership(description))
        self.assertTrue(description.endswith("]"))

    def test_invalid_and_future_markers_are_reported(self) -> None:
        with self.assertRaisesRegex(OwnershipMetadataError, "Malformed"):
            parse_ownership("Text\n\n[runplan:v1:not valid]")
        with self.assertRaisesRegex(OwnershipMetadataError, "Unsupported"):
            parse_ownership("[runplan:v2:e30]")

    def test_marker_must_be_the_description_suffix(self) -> None:
        with self.assertRaisesRegex(OwnershipMetadataError, "Malformed"):
            parse_ownership("[runplan:v1:e30]\nmore text")


if __name__ == "__main__":
    unittest.main()
