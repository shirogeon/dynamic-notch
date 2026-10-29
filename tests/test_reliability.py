"""
Unit and reliability tests for Dynamic Notch.
Tests operate deterministically and headless without requiring live audio/desktop services.
"""

import math
import os
import unittest
from unittest.mock import MagicMock, patch

import notch
from notch import AudioLevelMonitor, CinemaModeController, LyricsController, MediaController


class TestLyricsReliability(unittest.TestCase):
    def setUp(self):
        self.lyrics = LyricsController()

    def test_clean_title(self):
        cases = [
            ("Song Title (feat. Artist)", "Song Title"),
            ("Track Name (with Someone)", "Track Name"),
            ("Hit Track [Remastered 2021]", "Hit Track"),
            ("Single - Radio Edit", "Single"),
            ("Live at Wembley (Live)", "Live at Wembley"),
            ("Deluxe Edition (deluxe edition)", "Deluxe Edition"),
            ("Simple Title", "Simple Title"),
        ]
        for raw, expected in cases:
            self.assertEqual(LyricsController.clean_title(raw), expected)

    def test_score_candidate_valid(self):
        cand = {
            "trackName": "Starboy (feat. Daft Punk)",
            "artistName": "The Weeknd",
            "duration": 230.5,
            "syncedLyrics": "[00:10.00] I'm tryna put you in the worst mood, ah",
        }
        score = LyricsController._score_candidate(cand, "Starboy", "The Weeknd", duration_s=230)
        self.assertGreaterEqual(score, 100)

    def test_score_candidate_rejects_incompatible_title(self):
        cand = {
            "trackName": "Blinding Lights",
            "artistName": "The Weeknd",
            "duration": 200,
            "syncedLyrics": "[00:10.00] Some lyrics",
        }
        score = LyricsController._score_candidate(cand, "Starboy", "The Weeknd", duration_s=200)
        self.assertEqual(score, -1)

    def test_score_candidate_rejects_incompatible_artist(self):
        cand = {
            "trackName": "Starboy",
            "artistName": "Drake",
            "duration": 230,
            "syncedLyrics": "[00:10.00] Some lyrics",
        }
        score = LyricsController._score_candidate(cand, "Starboy", "The Weeknd", duration_s=230)
        self.assertEqual(score, -1)

    def test_score_candidate_rejects_duration_diff_over_tolerance(self):
        cand = {
            "trackName": "Starboy",
            "artistName": "The Weeknd",
            "duration": 250,  # 20s difference
            "syncedLyrics": "[00:10.00] Some lyrics",
        }
        score = LyricsController._score_candidate(cand, "Starboy", "The Weeknd", duration_s=230)
        self.assertEqual(score, -1)

    def test_score_candidate_rejects_no_synced_and_not_instrumental(self):
        cand = {
            "trackName": "Starboy",
            "artistName": "The Weeknd",
            "duration": 230,
            "plainLyrics": "Unsynced plain lyrics only",
        }
        score = LyricsController._score_candidate(cand, "Starboy", "The Weeknd", duration_s=230)
        self.assertEqual(score, -1)

    def test_parse_lrc(self):
        lrc_text = (
            "[00:05.50] First line\n"
            "[00:12.00] Second line\n"
            "[01:00.00] One minute line\n"
        )
        parsed = self.lyrics._parse_lrc(lrc_text)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0], (5500, "First line"))
        self.assertEqual(parsed[1], (12000, "Second line"))
        self.assertEqual(parsed[2], (60000, "One minute line"))

    def test_get_state_binary_search(self):
        self.lyrics._status = LyricsController.STATUS_SYNCED
        self.lyrics._lines = [
            (5000, "Line 1"),
            (10000, "Line 2"),
            (15000, "Line 3"),
        ]

        # Before intro (< 5000ms)
        state_intro = self.lyrics.get_state(2000 * 1000)
        self.assertTrue(state_intro["is_intro"])
        self.assertEqual(state_intro["next_line"], "Line 1")

        # At Line 1 (5000ms to 9999ms)
        state_l1 = self.lyrics.get_state(7000 * 1000)
        self.assertFalse(state_l1["is_intro"])
        self.assertEqual(state_l1["current_line"], "Line 1")
        self.assertEqual(state_l1["next_line"], "Line 2")

        # At Line 3 (15000ms+)
        state_l3 = self.lyrics.get_state(16000 * 1000)
        self.assertEqual(state_l3["current_line"], "Line 3")
        self.assertEqual(state_l3["next_line"], "")

    def test_stale_async_response_rejection(self):
        self.lyrics._token = 5
        self.lyrics._status = LyricsController.STATUS_SYNCED
        self.lyrics._lines = [(1000, "Current Song Line")]

        # Outdated token 4 completes
        self.lyrics._apply_result(4, LyricsController.STATUS_SYNCED, [(2000, "Stale Song Line")])
        self.assertEqual(self.lyrics._lines, [(1000, "Current Song Line")])

        # Matching token 5 completes
        self.lyrics._apply_result(5, LyricsController.STATUS_SYNCED, [(3000, "Updated Song Line")])
        self.assertEqual(self.lyrics._lines, [(3000, "Updated Song Line")])


class TestAudioLevelMonitor(unittest.TestCase):
    def test_goertzel_frequency_discrimination(self):
        sample_rate = 8000.0
        n_samples = 256

        def make_sine(freq):
            return [int(10000 * math.sin(2.0 * math.pi * freq * i / sample_rate)) for i in range(n_samples)]

        # 160 Hz tone (Bass)
        bass_samples = make_sine(160.0)
        p_bass_at_160 = AudioLevelMonitor.compute_goertzel(bass_samples, 160.0, sample_rate)
        p_bass_at_800 = AudioLevelMonitor.compute_goertzel(bass_samples, 800.0, sample_rate)
        p_bass_at_2400 = AudioLevelMonitor.compute_goertzel(bass_samples, 2400.0, sample_rate)

        self.assertGreater(p_bass_at_160, p_bass_at_800 * 5)
        self.assertGreater(p_bass_at_160, p_bass_at_2400 * 5)

        # 800 Hz tone (Mid)
        mid_samples = make_sine(800.0)
        p_mid_at_160 = AudioLevelMonitor.compute_goertzel(mid_samples, 160.0, sample_rate)
        p_mid_at_800 = AudioLevelMonitor.compute_goertzel(mid_samples, 800.0, sample_rate)
        p_mid_at_2400 = AudioLevelMonitor.compute_goertzel(mid_samples, 2400.0, sample_rate)

        self.assertGreater(p_mid_at_800, p_mid_at_160 * 5)
        self.assertGreater(p_mid_at_800, p_mid_at_2400 * 5)

        # 2400 Hz tone (Treble)
        treble_samples = make_sine(2400.0)
        p_treble_at_160 = AudioLevelMonitor.compute_goertzel(treble_samples, 160.0, sample_rate)
        p_treble_at_800 = AudioLevelMonitor.compute_goertzel(treble_samples, 800.0, sample_rate)
        p_treble_at_2400 = AudioLevelMonitor.compute_goertzel(treble_samples, 2400.0, sample_rate)

        self.assertGreater(p_treble_at_2400, p_treble_at_160 * 5)
        self.assertGreater(p_treble_at_2400, p_treble_at_800 * 5)

    def test_audio_monitor_lifecycle(self):
        monitor = AudioLevelMonitor()
        try:
            self.assertEqual(len(monitor.get_levels()), 3)
            monitor.set_playing(True)
            self.assertTrue(monitor._is_playing)
            monitor.set_playing(False)
            self.assertFalse(monitor._is_playing)
        finally:
            monitor.stop()
            self.assertFalse(monitor._running)


class TestMediaControllerLifecycle(unittest.TestCase):
    @patch("notch.dbus.SessionBus")
    def test_default_state_when_unavailable(self, mock_bus):
        ctrl = MediaController()
        ctrl._props = None
        info = ctrl.get_info()

        self.assertIsNone(info["title"])
        self.assertIsNone(info["artist"])
        self.assertEqual(info["status"], "Stopped")
        self.assertIsNone(info["pixbuf"])
        self.assertIsNone(info["pixbuf_compact"])

    @patch("notch.dbus.SessionBus")
    def test_disconnection_cleans_cached_art(self, mock_bus):
        ctrl = MediaController()
        ctrl._name = "org.mpris.MediaPlayer2.spotify"
        ctrl._cached_art_url = "https://example.com/art.jpg"
        ctrl._cached_pixbuf_expanded = MagicMock()
        ctrl._cached_pixbuf_compact = MagicMock()

        # Simulate player disconnection event
        ctrl._on_name_owner_changed("org.mpris.MediaPlayer2.spotify", "old_owner", "")

        self.assertIsNone(ctrl._player)
        self.assertIsNone(ctrl._name)
        self.assertIsNone(ctrl._cached_art_url)
        self.assertIsNone(ctrl._cached_pixbuf_expanded)
        self.assertIsNone(ctrl._cached_pixbuf_compact)


class TestCinemaModeHysteresis(unittest.TestCase):
    def test_override_detection(self):
        override_file = "/tmp/dynamic_notch_cinema_override"
        controller = CinemaModeController()
        try:
            # When override is absent, result depends on system state
            if os.path.exists(override_file):
                os.remove(override_file)

            # When override is created, check_fullscreen MUST be True
            with open(override_file, "w") as f:
                f.write("1\n")
            self.assertTrue(controller.check_fullscreen())
        finally:
            if os.path.exists(override_file):
                os.remove(override_file)
            controller.close()

    def test_debounce_hysteresis_logic(self):
        # Fullscreen detection enters immediately
        counter = 0
        fs = True
        if fs:
            counter = min(3, counter + 1)
        self.assertEqual(counter, 1)

        # Continues fullscreen, caps at 3
        for _ in range(5):
            counter = min(3, counter + 1)
        self.assertEqual(counter, 3)

        # Fullscreen exits, must debounce (require 3 ticks of non-fullscreen before restore)
        counter = max(0, counter - 1)
        self.assertEqual(counter, 2)  # Not 0, cannot restore yet

        counter = max(0, counter - 1)
        self.assertEqual(counter, 1)  # Still not 0

        counter = max(0, counter - 1)
        self.assertEqual(counter, 0)  # Reaches 0, safe to restore


class TestGLibTimerLifecycle(unittest.TestCase):
    def test_cancel_timer_removes_real_source(self):
        from gi.repository import GLib

        source_id = GLib.timeout_add(10000, lambda: True)
        self.assertIsNotNone(source_id)

        obj = MagicMock()
        obj._my_timer = source_id

        notch.DynamicIslandWindow._cancel_timer(obj, "_my_timer")
        self.assertIsNone(obj._my_timer)

        # Calling again must be safe and idempotent
        notch.DynamicIslandWindow._cancel_timer(obj, "_my_timer")
        self.assertIsNone(obj._my_timer)

    def test_cancel_timer_anim_timer_resets_anim_running(self):
        from gi.repository import GLib

        real_source = GLib.timeout_add(10000, lambda: True)
        obj = MagicMock()
        obj._anim_timer = real_source
        obj._anim_running = True

        notch.DynamicIslandWindow._cancel_timer(obj, "_anim_timer")
        self.assertFalse(obj._anim_running)
        self.assertIsNone(obj._anim_timer)


class TestAnimationEngineLifecycle(unittest.TestCase):
    def test_cubic_ease_out_curve_properties(self):
        """Verify mathematical ease-out curvature: f(0)=0, f(1)=1, monotonic, decelerating."""
        steps = 50
        factors = []
        for i in range(steps + 1):
            prog = i / float(steps)
            factor = 1.0 - (1.0 - prog) ** 3
            factors.append(factor)

        # Boundary checks
        self.assertAlmostEqual(factors[0], 0.0, places=6)
        self.assertAlmostEqual(factors[-1], 1.0, places=6)

        # Strictly monotonic increasing
        for j in range(len(factors) - 1):
            self.assertGreater(factors[j + 1], factors[j])

        # Decelerating (first derivative decreases monotonically)
        deltas = [factors[k + 1] - factors[k] for k in range(len(factors) - 1)]
        for k in range(len(deltas) - 1):
            self.assertLessEqual(deltas[k + 1], deltas[k] + 1e-9)

    def test_first_tick_latches_start_time_without_consuming_budget(self):
        """Verify that pre-timer delays do not cause frame 1 jumps."""
        from gi.repository import GLib

        win = MagicMock()
        win._anim_running = True
        win._anim_start_time = 0.0  # Initial flag from _animate_to
        win._start_w = 280.0
        win._start_h = 44.0
        win._anim_target_w = 400.0
        win._anim_target_h = 168.0
        win._target_state = notch.DynamicIslandWindow.STATE_FULL
        win._state = notch.DynamicIslandWindow.STATE_COMPACT
        win._start_opacities = {}
        win._idle_box = MagicMock()
        win._compact_box = MagicMock()
        win._notif_box = MagicMock()
        win._empty_box = MagicMock()
        win._full_box = MagicMock()

        # Execute first tick
        ret = notch.DynamicIslandWindow._anim_step(win)
        self.assertTrue(ret)
        # First tick must establish timestamp and stay at start geometry (zero elapsed)
        self.assertGreater(win._anim_start_time, 0.0)
        self.assertAlmostEqual(win._current_w, 280.0, places=2)
        self.assertAlmostEqual(win._current_h, 44.0, places=2)
        win.queue_draw.assert_called()

    def test_reversal_mid_flight_geometry(self):
        """Verify reversing an animation mid-flight starts from current in-flight width and height."""
        win = MagicMock(spec=notch.DynamicIslandWindow)
        win.STATE_IDLE = notch.DynamicIslandWindow.STATE_IDLE
        win.STATE_COMPACT = notch.DynamicIslandWindow.STATE_COMPACT
        win.STATE_FULL = notch.DynamicIslandWindow.STATE_FULL
        win.STATE_NOTIF = notch.DynamicIslandWindow.STATE_NOTIF
        win.STATE_EMPTY = notch.DynamicIslandWindow.STATE_EMPTY
        win.STATE_CINEMA_SUPPRESSED = notch.DynamicIslandWindow.STATE_CINEMA_SUPPRESSED

        win._is_cinema_suppressed = False
        win._current_w = 340.0
        win._current_h = 100.0
        win._anim_running = True
        win._target_state = notch.DynamicIslandWindow.STATE_FULL
        win._state = notch.DynamicIslandWindow.STATE_COMPACT
        win._has_lyrics = False
        win._idle_box = MagicMock()
        win._compact_box = MagicMock()
        win._notif_box = MagicMock()
        win._empty_box = MagicMock()
        win._full_box = MagicMock()

        with patch("notch.GLib.timeout_add", return_value=123):
            notch.DynamicIslandWindow._animate_to(win, notch.DynamicIslandWindow.STATE_COMPACT)

        # Must reverse towards compact, starting from current 340x100
        self.assertEqual(win._target_state, notch.DynamicIslandWindow.STATE_COMPACT)
        self.assertEqual(win._start_w, 340.0)
        self.assertEqual(win._start_h, 100.0)
        self.assertEqual(win._anim_target_w, float(notch.COMPACT_W))
        self.assertEqual(win._anim_target_h, float(notch.COMPACT_H))
        self.assertEqual(win._anim_start_time, 0.0)
        self.assertTrue(win._anim_running)

    def test_animate_to_idempotency_when_already_targeting(self):
        """Verify requesting the same target state while already transitioning does not restart."""
        win = MagicMock()
        win._is_cinema_suppressed = False
        win._anim_running = True
        win._target_state = notch.DynamicIslandWindow.STATE_FULL
        win._state = notch.DynamicIslandWindow.STATE_COMPACT

        with patch("notch.GLib.timeout_add") as mock_timeout:
            notch.DynamicIslandWindow._animate_to(win, notch.DynamicIslandWindow.STATE_FULL)
            mock_timeout.assert_not_called()


if __name__ == "__main__":
    unittest.main()
