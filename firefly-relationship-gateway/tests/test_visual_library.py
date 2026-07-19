import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from relationship_gateway.visual_assets import VisualLibraryStore


class VisualLibraryStoreTests(unittest.TestCase):
    def test_backgrounds_and_three_successful_chapter_cgs_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "user.png"
            Image.new("RGB", (8, 8), "#79bbaa").save(source)
            store = VisualLibraryStore(root / "data")

            added = store.add_background(source)
            enabled = [item["id"] for item in store.backgrounds() if item["enabled"]]
            self.assertIn(added["id"], enabled)
            store.set_enabled_backgrounds([added["id"]])
            self.assertEqual([item["id"] for item in store.backgrounds() if item["enabled"]], [added["id"]])

            self.assertIsNone(store.create_chapter_job("chapter-1", "第一章", "prompt"))
            self.assertTrue(store.chapter_cg_status("chapter-1")["has_brief"])
            store.set_image_model_available(True)
            for index in range(3):
                job = store.create_chapter_job("chapter-1")
                self.assertIsNotNone(job)
                assert job is not None
                self.assertIsNone(store.create_chapter_job("chapter-1"))
                pending = store.pending_chapter_job()
                assert pending is not None
                self.assertEqual(Path(pending["attachments"][0]).name, "firefly-face-reference.png")
                self.assertTrue(Path(pending["attachments"][0]).is_file())
                output = Path(pending["output_path"])
                output.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (8, 8), f"#{index + 2}9bbaa").save(output)
                self.assertTrue(store.finish_chapter_job(job["id"]))
            self.assertIsNone(store.create_chapter_job("chapter-1"))
            self.assertEqual(len(store.chapter_cgs()), 3)
            first = store.chapter_cgs()[0]
            store.set_chapter_cg_selected(str(first["id"]), False)
            self.assertFalse(store.chapter_cgs()[0]["selected"])
            second, third = store.chapter_cgs()[1:]
            store.set_chapter_cg_selected(str(second["id"]), False)
            store.set_chapter_cg_selected(str(third["id"]), False)
            self.assertEqual(sum(item["selected"] for item in store.chapter_cgs()), 1)
            self.assertEqual(store.chapter_cg_status("chapter-1")["remaining"], 0)

            store.set_enabled_backgrounds(["firefly-title-background"])
            store.delete_background(added["id"])
            self.assertFalse(Path(store._data_path(added["file"])).exists())

    def test_failed_generation_keeps_the_brief_and_success_quota(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VisualLibraryStore(Path(directory) / "data")
            store.save_chapter_brief("chapter-1", "第一章", "personal prompt")
            store.set_image_model_available(True)
            job = store.create_chapter_job("chapter-1")
            assert job is not None

            self.assertTrue(store.finish_chapter_job(str(job["id"]), "provider error"))

            status = store.chapter_cg_status("chapter-1")
            self.assertEqual((status["count"], status["remaining"], status["pending"]), (0, 3, False))
            self.assertEqual(status["last_error"], "provider error")
            self.assertIsNotNone(store.create_chapter_job("chapter-1"))

    def test_version_one_library_is_migrated_without_losing_existing_cg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            image = root / "visuals" / "chapter-cg" / "chapter-1.png"
            image.parent.mkdir(parents=True)
            Image.new("RGB", (8, 8), "#79bbaa").save(image)
            root.joinpath("visual-library.json").write_text(json.dumps({
                "version": 1,
                "enabled_background_ids": ["firefly-title-background"],
                "user_backgrounds": [],
                "story_cgs": [],
                "chapter_cgs": [{"chapter_id": "chapter-1", "title": "第一章", "file": "visuals/chapter-cg/chapter-1.png"}],
                "chapter_jobs": [],
                "image_model_available": False,
            }), encoding="utf-8")

            store = VisualLibraryStore(root)

            self.assertEqual(store.load()["version"], 2)
            self.assertEqual(len(store.chapter_cgs()), 1)
            self.assertTrue(store.chapter_cgs()[0]["selected"])


if __name__ == "__main__":
    unittest.main()
