import json
import tarfile
import tempfile
import unittest
from cStringIO import StringIO
from mock import patch, MagicMock

from .squash import get_squash_layers, download_layers_for_image, \
    extract_layer_tar, apply_layer, rewrite_image_parent


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
    def test_extraction(self, tempfile, _tarfile, mock_open):

        tar_fh = extract_layer_tar('/tmp', _tarfile, 'A')
        self.assertEqual(tar_fh, 'fh')

        _tarfile.extract.assert_called_with(
            member='A/layer.tar',
            path='/tmp/path'
        )


class ApplyLayerTestCase(unittest.TestCase):

    def test_apply_single_layer_added_files(self):

        extracted, touched, dirs, seen = self._apply_layer(files=[
            tarfile.TarInfo("a"),
            tarfile.TarInfo("b"),
            tarfile.TarInfo("c/d"),
        ], seen_paths=set())

        self.assertListEqual(extracted, ["a", "b", "c/d"])
        self.assertListEqual(touched, [])
        self.assertListEqual(dirs, [])
        self.assertSetEqual(seen, {"a", "b", "c/d"})

    def test_apply_single_layer_deleted_files(self):

        extracted, touched, dirs, seen = self._apply_layer(files=[
            tarfile.TarInfo(".wh.a"),
            tarfile.TarInfo(".wh.b"),
            tarfile.TarInfo("c/.wh.d"),
        ], seen_paths=set())

        self.assertListEqual(extracted, [])
        self.assertListEqual(touched, [".wh.a", ".wh.b", 'c/.wh.d'])
        self.assertListEqual(dirs, ['c'])
        self.assertSetEqual(seen, {"a", "b", "c/d"})

    def test_apply_single_layer_no_files(self):

        extracted, touched, dirs, seen = self._apply_layer(files=[], seen_paths=set())

        self.assertListEqual(extracted, [])
        self.assertListEqual(touched, [])
        self.assertListEqual(dirs, [])
        self.assertSetEqual(seen, set())

    def test_apply_multiple_layers_added_files(self):

        extracted, touched, dirs, seen = self._apply_layers(layers=[
            [
                tarfile.TarInfo("a"),
                tarfile.TarInfo("c/d"),
            ],
            [
                tarfile.TarInfo("b"),
                tarfile.TarInfo("c/e"),
            ]
        ])

        self.assertListEqual(extracted, ["a", "c/d", "b", "c/e"])
        self.assertListEqual(touched, [])
        self.assertListEqual(dirs, [])
        self.assertSetEqual(seen, {"a", "c/d", "b", "c/e"})

    def test_apply_multiple_layers_deleted_files(self):

        extracted, touched, dirs, seen = self._apply_layers(layers=[
            [
                tarfile.TarInfo(".wh.a"),
            ],
            [
                tarfile.TarInfo(".wh.b"),
                tarfile.TarInfo("c/.wh.d"),
            ]
        ])

        self.assertListEqual(extracted, [])
        self.assertListEqual(touched, [".wh.a", ".wh.b", "c/.wh.d"])
        self.assertListEqual(dirs, ["c"])
        self.assertSetEqual(seen, {"a", "b", "c/d"})

    def test_apply_multiple_layers_mixed(self):

        extracted, touched, dirs, seen = self._apply_layers(layers=[
            [
                tarfile.TarInfo("a"),
            ],
            [
                tarfile.TarInfo("b"),
                tarfile.TarInfo("c/e"),
                tarfile.TarInfo(".wh.a"),
                tarfile.TarInfo(".wh.f"),
            ],
            [
                tarfile.TarInfo("a"),
                tarfile.TarInfo("c/d"),
                tarfile.TarInfo(".wh.b"),
            ]
        ])

        self.assertListEqual(extracted, ["a", "b", "c/e", "c/d"])
        self.assertListEqual(touched, [".wh.f"])
        self.assertListEqual(dirs, [])
        self.assertSetEqual(seen, {"a", "b", "c/e", "f", "c/d"})

    def test_apply_multiple_layers_add_remove(self):

        extracted, touched, dirs, seen = self._apply_layers(layers=[
            [
                tarfile.TarInfo(".wh.a"),
            ],
            [
                tarfile.TarInfo("a"),
            ]
        ])

        self.assertListEqual(extracted, [])
        self.assertListEqual(touched, [".wh.a"])
        self.assertListEqual(dirs, [])
        self.assertSetEqual(seen, {"a"})

    def test_apply_multiple_layers_remove_add(self):

        extracted, touched, dirs, seen = self._apply_layers(layers=[
            [
                tarfile.TarInfo("a"),
            ],
            [
                tarfile.TarInfo(".wh.a"),
            ]
        ])

        self.assertListEqual(extracted, ["a"])
        self.assertListEqual(touched, [])
        self.assertListEqual(dirs, [])
        self.assertSetEqual(seen, {"a"})

    def _apply_layer(self, files, seen_paths):

        extracted_files = []
        touched_files = []
        new_dirs = []

        def extract_file(member, path):
            extracted_files.append(member)

        def touch_file(path):
            # Remove the /tmp/ prefix to make writing tests simpler
            touched_files.append(path[4:].lstrip("/"))

        def make_dir(path):
            # Remove the /tmp/ prefix to make writing tests simpler
            new_dirs.append(path[4:].lstrip("/"))

        with patch("portainer.util.squash.touch", side_effect=touch_file):
            with patch("portainer.util.squash.mkdir_p", side_effect=make_dir):
                with tempfile.TemporaryFile() as tar_fh:
                    tar = tarfile.open(fileobj=tar_fh, mode="w")

                    for info in files:
                        tar.addfile(info, fileobj=StringIO("\x00"))

                    tar.extract = MagicMock(side_effect=extract_file)

                    return (
                        extracted_files,
                        touched_files,
                        new_dirs,
                        apply_layer('/tmp', tar, seen_paths)
                    )

    def _apply_layers(self, layers):

        extracted_files = []
        touched_files = []
        new_dirs = []
        seen_paths = set()

        for files in layers:
            e, t, n, p = self._apply_layer(files, seen_paths)

            extracted_files.extend(e)
            touched_files.extend(t)
            new_dirs.extend(n)
            seen_paths.update(p)

        return (
            extracted_files,
            touched_files,
            new_dirs,
            seen_paths
        )


class RewriteImageParentTestCase(unittest.TestCase):

    def test_rewrite_parent(self):

        self.assertDictEqual(rewrite_image_parent({
            "parent": None,
            "config": {},
            "container_config": {}
        }, "A"), {
            "parent": "A",
            "config": {
                "Image": "A"
            },
            "container_config": {
                "Image": "A"
            }
        })
