from datetime import datetime

import pytest

import github.internals.entities as e


def create_with_state(state):
    return e.Status("c", "d", state, "")


def create_with_description(description):
    return e.Status("c", description, e.State.PENDING, "")


class TestStatus(object):
    def test_from_dict(self):
        d = {
            "context": "c",
            "description": "d",
            "state": "PENDING",
            "targetUrl": ""
        }

        assert e.Status.from_dict(d) == e.Status("c", "d", e.State.PENDING, "")

    @pytest.mark.parametrize("test_input,expected", [
        (create_with_state(e.State.PENDING), True),
        (create_with_state(e.State.FAILURE), False),
        (create_with_state(e.State.ERROR), False),
        (create_with_state(e.State.SUCCESS), False)
    ])
    def test_pending(self, test_input, expected):
        assert test_input.pending == expected

    @pytest.mark.parametrize("test_input,expected", [
        (create_with_state(e.State.PENDING), False),
        (create_with_state(e.State.FAILURE), False),
        (create_with_state(e.State.ERROR), False),
        (create_with_state(e.State.SUCCESS), True)
    ])
    def test_succeeded(self, test_input, expected):
        assert test_input.succeeded == expected

    @pytest.mark.parametrize("test_input,expected", [
        (create_with_state(e.State.PENDING), False),
        (create_with_state(e.State.FAILURE), True),
        (create_with_state(e.State.ERROR), True),
        (create_with_state(e.State.SUCCESS), False)
    ])
    def test_failed(self, test_input, expected):
        assert test_input.failed == expected

    @pytest.mark.parametrize("test_input,expected", [
        (create_with_description(""), False),
        (create_with_description("TaKeN"), True),
        (create_with_description("Blablabla"), False),
        (create_with_description("unassigned"), False)
    ])
    def test_taken(self, test_input, expected):
        assert test_input.taken == expected

    @pytest.mark.parametrize("test_input,expected", [
        (create_with_description(""), False),
        (create_with_description("TaKeN"), False),
        (create_with_description("Blablabla"), False),
        (create_with_description(e.RERUN_PENDING), True),
        (create_with_description("unassigned"), False)
    ])
    def test_rerun_pending(self, test_input, expected):
        assert test_input.rerun_pending == expected

    @pytest.mark.parametrize("test_input,expected", [
        (create_with_description(""), False),
        (create_with_description("TaKeN"), False),
        (create_with_description("Blablabla"), False),
        (create_with_description(e.RERUN_PENDING), False),
        (create_with_description("unassigned"), True)
    ])
    def test_unassigned(self, test_input, expected):
        assert test_input.unassigned == expected
