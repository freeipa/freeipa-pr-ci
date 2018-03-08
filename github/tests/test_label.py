import pytest

import github.internals.entities as e


class TestLabel(object):
    @pytest.mark.parametrize("test_input,expected", [
        ("ack", e.Label.ACK),
        ("blacklisted", e.Label.BLACKLIST),
        ("postponed", e.Label.POSTPONE),
        ("re-run", e.Label.RERUN),
        ("needs rebase", e.Label.REBASE),
        ("wrong label", None)
    ])
    def test_from_str(self, test_input, expected):
        assert e.Label.from_str(test_input) == expected
