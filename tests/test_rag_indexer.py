import os
import unittest
from pathlib import Path
from unittest.mock import patch
import uuid
import shutil

from rag import indexer


class RagIndexerTests(unittest.TestCase):
    def _make_workspace_tempdir(self) -> Path:
        path = (Path("tests/.tmp") / uuid.uuid4().hex).resolve()
        path.mkdir(parents=True, exist_ok=False)
        self.addCleanup(lambda: shutil.rmtree(path, ignore_errors=True))
        return path

    def test_clear_directory_contents_keeps_root_directory(self):
        tmpdir = self._make_workspace_tempdir()
        root = tmpdir / "data" / "chroma"
        nested_dir = root / "nested"
        nested_dir.mkdir(parents=True)
        (root / "root.bin").write_text("x", encoding="utf-8")
        (nested_dir / "child.bin").write_text("y", encoding="utf-8")

        indexer._clear_directory_contents(root)

        self.assertTrue(root.exists())
        self.assertTrue(root.is_dir())
        self.assertEqual(list(root.iterdir()), [])

    def test_rebuild_keeps_chroma_mount_point_and_clears_generated_files(self):
        tmpdir = self._make_workspace_tempdir()
        original_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            chroma_dir = tmpdir / "data" / "chroma"
            chroma_dir.mkdir(parents=True)
            (chroma_dir / "segment.bin").write_text("segment", encoding="utf-8")

            cache_dir = tmpdir / "data" / "cache"
            cache_dir.mkdir(parents=True)
            (cache_dir / "bm25.pkl").write_text("cache", encoding="utf-8")

            exports_dir = tmpdir / "data" / "exports"
            exports_dir.mkdir(parents=True)
            (exports_dir / "chunks.json").write_text("old", encoding="utf-8")

            with patch.object(indexer.settings, "chroma_persist_dir", str(chroma_dir)):
                with patch("rag.indexer.reset_collection") as mock_reset:
                    with patch("rag.indexer.build_knowledge_base", return_value={"documents": 1, "chunks": 2}) as mock_build:
                        result = indexer.rebuild_knowledge_base()

            self.assertEqual(result, {"documents": 1, "chunks": 2})
            self.assertTrue(chroma_dir.exists())
            self.assertEqual(list(chroma_dir.iterdir()), [])
            self.assertFalse((cache_dir / "bm25.pkl").exists())
            self.assertFalse((exports_dir / "chunks.json").exists())
            mock_reset.assert_called_once()
            mock_build.assert_called_once()
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
