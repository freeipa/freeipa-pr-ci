import pytest

import github.internals.entities as e


@pytest.fixture()
def expected_pr():
    return e.PullRequest(
        1, "me", "master", "CONFLICTING",
        ["re-run"], {"oid": "blabla"}
    )


def create_with_label(label):
    return e.PullRequest(
        1, "me", "master", "CONFLICTING", [label], {"oid": "blabla"}
    )


class TestPullRequest(object):
    def test_from_dict(self, expected_pr):
        d = {
            "number": 1,
            "author": {"login": "me"},
            "baseRefName": "master",
            "mergeable": "CONFLICTING",
            "labels": {
                "nodes": [{"name": "re-run"}]
            },
            "commits": {
                "nodes": [{
                    "commit": {
                        "oid": "blabla"
                    }
                }]
            }
        }
        pr = e.PullRequest.from_dict(d)
        assert pr == expected_pr

    @pytest.mark.parametrize("test_input,expected", [
        (create_with_label("ack"), True),
        (create_with_label("postponed"), False),
        (create_with_label("re-run"), False),
        (create_with_label("needs rebase"), False),
        (create_with_label("prioritized"), False)
    ])
    def test_acked(self, test_input, expected):
        assert test_input.acked == expected

    @pytest.mark.parametrize("test_input,expected", [
        (create_with_label("ack"), False),
        (create_with_label("postponed"), True),
        (create_with_label("re-run"), False),
        (create_with_label("needs rebase"), False),
        (create_with_label("prioritized"), False)
    ])
    def test_postponed(self, test_input, expected):
        assert test_input.postponed == expected

    @pytest.mark.parametrize("test_input,expected", [
        (create_with_label("ack"), False),
        (create_with_label("postponed"), False),
        (create_with_label("re-run"), False),
        (create_with_label("needs rebase"), True),
        (create_with_label("prioritized"), False)
    ])
    def test_needs_rebase(self, test_input, expected):
        assert test_input.needs_rebase == expected

    @pytest.mark.parametrize("test_input,expected", [
        (create_with_label("ack"), False),
        (create_with_label("postponed"), False),
        (create_with_label("re-run"), False),
        (create_with_label("needs rebase"), False),
        (create_with_label("prioritized"), True)
    ])
    def test_prioritized(self, test_input, expected):
        assert test_input.prioritized == expected
