"""One fresh lstat witnesses both path type and the five artifact identity fields."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
from pokemon_index import catalog_read_model_artifact as artifact


class ArtifactAtomicIdentityTests(unittest.TestCase):
    def test_same_witness_drives_symlink_rejection_and_identity_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'artifact'; path.write_bytes(b'synthetic only')
            link = Path(tmp)/'symlink'; link.symlink_to(path)
            real = os.lstat(path); symlink = os.lstat(link)
            with patch.object(artifact.os, 'lstat', return_value=real) as witness:
                self.assertEqual(artifact._file_identity(path), (real.st_dev, real.st_ino, real.st_size, real.st_mtime_ns, real.st_ctime_ns))
                witness.assert_called_once_with(path)
            # A final-component symlink may point to the very same inode. The
            # observed path type must still reject rather than follow a stat.
            with patch.object(artifact.os, 'lstat', return_value=symlink) as witness:
                with self.assertRaises(artifact.ArtifactInvalid): artifact._file_identity(path)
                witness.assert_called_once_with(path)

    def test_filesystem_replacement_and_nonregular_paths_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'artifact'; path.write_bytes(b'synthetic A')
            before = artifact._file_identity(path)
            replacement = Path(tmp)/'replacement'; replacement.write_bytes(b'synthetic B')
            os.replace(replacement, path)
            self.assertNotEqual(artifact._file_identity(path), before)
            path.unlink(); path.symlink_to(Path(tmp))
            with self.assertRaises(artifact.ArtifactInvalid): artifact._file_identity(path)
            with self.assertRaises(artifact.ArtifactInvalid): artifact._file_identity(Path(tmp))
            path.unlink(); os.mkfifo(path)
            with self.assertRaises(artifact.ArtifactInvalid): artifact._file_identity(path)
            path.unlink()
            with self.assertRaises(FileNotFoundError): artifact._file_identity(path)


if __name__ == '__main__': unittest.main()
