"""Large archive validation must retain integrity without whole-file reads."""
import hashlib
import importlib.util
import io
from pathlib import Path
import unittest
import zipfile

spec = importlib.util.spec_from_file_location(
    "validate_library", Path(__file__).resolve().parents[1] / "scripts/validate_library.py"
)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class BoundedStream(io.BytesIO):
    def read(self, size=-1):
        if not 0 < size <= 1024 * 1024:
            raise AssertionError(f"unbounded read: {size}")
        return super().read(size)


class StreamValidationTests(unittest.TestCase):
    def test_empty_and_multichunk_payloads_keep_exact_size_and_digest(self):
        for data in (b"", b"small", b"abc123" * 600_000):
            with self.subTest(size=len(data)):
                self.assertEqual(
                    validator._stream_digest(BoundedStream(data)),
                    (len(data), hashlib.sha256(data).hexdigest()),
                )

    def test_compressed_blob_stream_checks_uncompressed_bytes(self):
        data = b"synthetic asset" * 200_000
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("blob", data)
        buffer.seek(0)
        with zipfile.ZipFile(buffer) as archive, archive.open("blob") as stream:
            self.assertEqual(
                validator._stream_digest(stream),
                (len(data), hashlib.sha256(data).hexdigest()),
            )


if __name__ == "__main__":
    unittest.main()
