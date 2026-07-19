import tempfile
import unittest
import wave
from pathlib import Path

from relationship_gateway.playback import StoryPlaybackStore, is_cinematic_line, story_line_key
from relationship_gateway.panel import AMBIENT_FILES, BGM_FILES
from relationship_gateway.state import StoryLine


class StoryPlaybackTests(unittest.TestCase):
    def test_settings_and_read_lines_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StoryPlaybackStore(Path(directory))
            line = StoryLine("流萤", "下次还可以再见吗？", "shy")

            store.update_settings(text_speed_ms=18, auto_wait_ms=900, bgm_volume=62)
            store.mark_read(line)

            value = store.load()
            self.assertEqual((value["text_speed_ms"], value["auto_wait_ms"], value["bgm_volume"]), (18, 900, 62))
            self.assertTrue(store.is_read(line))
            self.assertEqual(len(story_line_key(line)), 24)

    def test_cinematic_lines_require_narration_and_a_real_stage_change(self) -> None:
        self.assertTrue(is_cinematic_line(StoryLine("旁白", "你们离开店里，来到雨后的街道。", "neutral")))
        self.assertFalse(is_cinematic_line(StoryLine("流萤", "我刚才只是提到了书店。", "neutral")))

    def test_chapter_audio_assets_are_valid_loop_sources(self) -> None:
        for path in (*BGM_FILES.values(), *AMBIENT_FILES.values()):
            with wave.open(str(path), "rb") as source:
                self.assertEqual((source.getnchannels(), source.getsampwidth(), source.getframerate()), (1, 2, 22_050))
                self.assertGreater(source.getnframes(), 22_050 * 15)


if __name__ == "__main__":
    unittest.main()
