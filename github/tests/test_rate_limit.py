from time import time

import pytest

import github.internals.entities as e


class TestRateLimit(object):
    def test_from_dict(self):
        d = {"limit": 123, "remaining": 50, "reset": int(time())}
        rl = e.RateLimit.from_dict(d)
        assert rl.limit == d["limit"]
        assert rl.remaining == d["remaining"]
        assert rl.reset_at == d["reset"]

    @pytest.mark.parametrize("test_input,expected", [
        (e.RateLimit(0, 0, time()), False),
        (e.RateLimit(0, e.EPHEMERAL_LIMIT, time()), True),
        (e.RateLimit(0, e.EPHEMERAL_LIMIT + 1, time()), True)
    ])
    def test_available(self, test_input, expected):
        assert test_input.available == expected

