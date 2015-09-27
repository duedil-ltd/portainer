import json
import unittest
from mock import patch

from .squash import get_squash_layers, download_layers_for_image, extract_layer_tar


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


@patch('docker.client.Client')
@patch('requests.Response')
class DownloadImageLayersTestCase(unittest.TestCase):

    def test_download_image_layers(self, docker, response):

        docker.get_image.return_value = response
        response.stream.return_value = "\x00\x00\x00\x00"

        fh = download_layers_for_image(docker, "/tmp", "A")
        docker.get_image.assert_called_with("A")

        self.assertEqual(fh.tell(), 0)
        self.assertEqual(fh.read(4), "\x00\x00\x00\x00")
        self.assertEqual(fh.read(1), "")

        fh.close()


@patch('tarfile.TarFile')
class LayerExctractionFromTarTestCase(unittest.TestCase):

    @patch('portainer.util.squash.tempfile.mkdtemp', return_value="/tmp/path")
    @patch('portainer.util.squash.open', return_value='fh')
    def test_extraction(self, tempfile, tarfile, mock_open):

        tar_fh = extract_layer_tar('/tmp', tarfile, 'A')
        self.assertEqual(tar_fh, 'fh')

        tarfile.extract.assert_called_with(
            member='A/layer.tar',
            path='/tmp/path'
        )
