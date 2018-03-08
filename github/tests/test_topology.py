import pytest

from github.internals.entities import Topology


class TestTopology(object):
    @pytest.mark.parametrize("test_input,expected", [
        ({"memory": 1, "cpu": 1}, Topology(memory=1, cpu=1)),
        (
            {"name": "topo", "memory": 1, "cpu": 1},
            Topology(name="topo", memory=1, cpu=1)
        )
    ])
    def test_from_dict(self, test_input, expected):
        assert Topology.from_dict(test_input) == expected
