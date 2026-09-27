import unittest
from jki.text import WakeGate, effort_choice, model_choice, speakable
from jki.media import music_query
from jki.speech_queue import SpeechQueue
from jki.state import Metrics, RecentIDs, Speech


class TextTests(unittest.TestCase):
    def test_background_speech_is_ignored(self):
        gate = WakeGate()
        for text in ["open terminal", "the jacket is blue", "switch to sol"]:
            self.assertIsNone(gate.accept(text, now=100))

    def test_whole_wake_word_and_followup(self):
        gate = WakeGate()
        self.assertEqual(gate.accept("hey jake open the terminal", now=100), "open the terminal")
        self.assertEqual(gate.accept("jake", now=100), "")
        self.assertEqual(gate.accept("what time is it", now=105), "what time is it")
        self.assertIsNone(gate.accept("another command", now=106))
        gate.accept("jake", now=200)
        self.assertIsNone(gate.accept("too late", now=213))

    def test_low_or_missing_confidence_rejected(self):
        self.assertIsNone(WakeGate().accept("jake open files", words=[{"word": "jake", "conf": .3}]))
        self.assertIsNone(WakeGate().accept("jake open files", words=[]))

    def test_model_selection_uses_catalog(self):
        models = ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.5", "future-catalog-model"]
        self.assertEqual(model_choice("switch to soul", models), "gpt-6-sol")
        self.assertEqual(model_choice("switch model to g p t five point six sol", models), "gpt-5.6-sol")
        self.assertEqual(model_choice("select future-catalog-model", models), "future-catalog-model")
        self.assertEqual(model_choice("switch model to gpt seven", models), "")
        self.assertIsNone(model_choice("change the wallpaper", models))

    def test_explicit_reasoning_selection_uses_supported_levels(self):
        levels = ["low", "medium", "high", "xhigh", "max"]
        self.assertEqual(effort_choice("set reasoning effort to max", levels), "max")
        self.assertEqual(effort_choice("change thinking to extra high", levels), "xhigh")
        self.assertEqual(effort_choice("use Sol with high reasoning", levels), "high")
        self.assertEqual(effort_choice("set reasoning to ultra", levels), "")
        self.assertIsNone(effort_choice("that was a high quality answer", levels))
        self.assertIsNone(effort_choice("explain high-level reasoning", levels))

    def test_speech_omits_code_and_link_targets(self):
        value = speakable("**Done.** [report](/private/file)\n```python\nprint('code')\n```")
        self.assertIn("Done.", value)
        self.assertNotIn("private", value)
        self.assertNotIn("print", value)

    def test_music_requests_respect_named_application(self):
        self.assertEqual(music_query("play the song take on me by a ha"), "take on me by a ha")
        self.assertIsNone(music_query("play take on me on spotify"))
        self.assertIsNone(music_query("play a chess game"))

    def test_progress_queue_coalesces(self):
        queue = SpeechQueue()
        queue.put(Speech("accepted", 0, "t"))
        for i in range(100):
            queue.put(Speech(str(i), 0, "t", progress=True))
        self.assertEqual(queue.qsize(), 2)
        self.assertEqual(queue.get_nowait().text, "accepted")
        self.assertEqual(queue.get_nowait().text, "99")

    def test_final_answer_removes_queued_progress(self):
        queue = SpeechQueue()
        queue.put(Speech("old progress", 0, "t", progress=True))
        queue.put(Speech("finished", 0, "t"))
        self.assertEqual(queue.qsize(), 1)
        self.assertEqual(queue.get_nowait().text, "finished")

    def test_recent_ids_are_bounded(self):
        recent = RecentIDs(5)
        for n in range(20):
            self.assertTrue(recent.add(str(n)))
        self.assertEqual(len(recent), 5)
        self.assertFalse(recent.add("19"))

    def test_metrics_are_bounded_and_ignore_nonfinite_values(self):
        metrics = Metrics(5)
        for n in range(20):
            metrics.record("latency", n)
        metrics.record("latency", float("nan"))
        self.assertEqual(metrics.snapshot()["latency"]["count"], 5)
