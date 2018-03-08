import pytest

import github.internals.entities as e


class TestState(object):
    @pytest.mark.parametrize("test_input,expected", [
        ("PENDING", e.State.PENDING),
        ("FAILURE", e.State.FAILURE),
        ("SUCCESS", e.State.SUCCESS),
        ("ERROR", e.State.ERROR),
        ("wrong state", None)
    ])
    def test_from_str(self, test_input, expected):
        assert e.State.from_str(test_input) == expected
