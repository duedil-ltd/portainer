import json
import unittest
from mock import patch

from .squash import get_squash_layers


@patch('docker.client.Client')
class SquashLayersTestCase(unittest.TestCase):

    def test_get_squash_layers_bottom(self, docker):
        self._mock_squash(docker, "A", "A", ["_A"])

    def test_get_squash_layers_direct_parent(self, docker):
        self._mock_squash(docker, "A", "B", ["_B", "_A"])

    def test_get_squash_layers_many(self, docker):
        self._mock_squash(docker, "A", "D", ["_D", "_C", "_B", "_A"])

    def _mock_squash(self, docker, base_image, head_image, lineage):

        docker.inspect_image.side_effect = lambda id: {
            "Id": "_%s" % id
        }

        docker.history.return_value = json.dumps([
            {
                "Id": id,
                "Size": 1024
            } for id in lineage
        ])

        new_base_image, new_head_image, size, layers = get_squash_layers(
            docker, base_image, head_image
        )

        self.assertEqual(new_base_image, "_%s" % base_image)
        self.assertEqual(new_head_image, "_%s" % head_image)
        self.assertEqual(size, 1024 * (len(lineage) - 1))
        self.assertListEqual(layers, lineage[:-1])
