"""
Unit and reliability tests for Dynamic Notch.
Tests operate deterministically and headless without requiring live audio/desktop services.
"""

import math
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

try:
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
except Exception:
    pass

import notch
from notch import (
    AudioLevelMonitor,
    BiquadBandpass,
    CinemaModeController,
    LyricsController,
    MediaController,
)


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

    @patch("notch.subprocess.Popen")
    @patch("notch.shutil.which", return_value="/usr/bin/pw-record")
    def test_initial_monitoring_of_laptop_speaker(self, mock_which, mock_popen):
        """Verify initial monitor startup targets laptop speaker sink monitor."""
        proc = MagicMock()
        proc.poll.return_value = None
        proc.stdout.read.return_value = b""
        mock_popen.return_value = proc

        with patch.object(AudioLevelMonitor, "get_default_sink_info", return_value=("alsa_output.pci-0000_04_00.6.analog-stereo", "Ryzen HD Audio")):
            with patch.object(AudioLevelMonitor, "get_recorder_sources", return_value={"alsa_output.pci-0000_04_00.6.analog-stereo:monitor_FL"}):
                mon = AudioLevelMonitor()
                try:
                    import time
                    t0 = time.time()
                    while time.time() - t0 < 0.5:
                        if mon._proc is not None:
                            break
                        time.sleep(0.02)
                    self.assertIsNotNone(mon._proc)
                    call_cmd = mock_popen.call_args[0][0]
                    self.assertIn("--media-category=Monitor", call_cmd)
                    self.assertIn("{ stream.capture.sink: true }", call_cmd)
                    self.assertIn("@DEFAULT_AUDIO_SINK@", call_cmd)
                finally:
                    mon.stop()

    @patch("notch.subprocess.Popen")
    @patch("notch.shutil.which", return_value="/usr/bin/pw-record")
    def test_initial_monitoring_when_tws_is_default_sink(self, mock_which, mock_popen):
        """Verify initial monitor startup targets Bluetooth TWS sink monitor when TWS is default."""
        proc = MagicMock()
        proc.poll.return_value = None
        proc.stdout.read.return_value = b""
        mock_popen.return_value = proc

        with patch.object(AudioLevelMonitor, "get_default_sink_info", return_value=("bluez_output.A4:C1:39:AA:43:78", "soundcore R60i NC")):
            with patch.object(AudioLevelMonitor, "get_recorder_sources", return_value={"bluez_output.A4:C1:39:AA:43:78:monitor_FL"}):
                mon = AudioLevelMonitor()
                try:
                    import time
                    t0 = time.time()
                    while time.time() - t0 < 0.5:
                        if mon._proc is not None:
                            break
                        time.sleep(0.02)
                    self.assertIn("soundcore R60i NC", mon.get_source_name())
                finally:
                    mon.stop()

    def test_switching_from_laptop_speakers_to_tws(self):
        """Verify switching default sink from speakers to TWS triggers recorder restart."""
        mon = AudioLevelMonitor.__new__(AudioLevelMonitor)
        import threading
        mon._lock = threading.Lock()
        mon._running = True
        mon._current_sink_name = "alsa_output.pci-0000_04_00.6.analog-stereo"
        mon._source_name = "Speakers"
        mon._restart_requested = False
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        mon._proc = fake_proc

        with patch.object(mon, "get_default_sink_info", return_value=("bluez_output.A4:C1:39:AA:43:78", "soundcore R60i NC")):
            with patch.object(mon, "get_recorder_sources", return_value={"alsa_output.pci-0000_04_00.6.analog-stereo:monitor_FL"}):
                mon.check_default_sink()
                self.assertTrue(mon._restart_requested)
                fake_proc.terminate.assert_called_once()

    def test_switching_from_tws_back_to_laptop_speakers(self):
        """Verify switching default sink from TWS back to speakers triggers recorder restart."""
        mon = AudioLevelMonitor.__new__(AudioLevelMonitor)
        import threading
        mon._lock = threading.Lock()
        mon._running = True
        mon._current_sink_name = "bluez_output.A4:C1:39:AA:43:78"
        mon._source_name = "TWS"
        mon._restart_requested = False
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        mon._proc = fake_proc

        with patch.object(mon, "get_default_sink_info", return_value=("alsa_output.pci-0000_04_00.6.analog-stereo", "Ryzen HD Audio")):
            with patch.object(mon, "get_recorder_sources", return_value={"bluez_output.A4:C1:39:AA:43:78:monitor_FL"}):
                mon.check_default_sink()
                self.assertTrue(mon._restart_requested)
                fake_proc.terminate.assert_called_once()

    def test_disconnecting_tws_during_capture(self):
        """Verify device disconnection terminating pw-record is detected and triggers restart."""
        mon = AudioLevelMonitor.__new__(AudioLevelMonitor)
        import threading
        mon._lock = threading.Lock()
        mon._running = True
        mon._current_sink_name = "bluez_output.A4:C1:39:AA:43:78"
        mon._restart_requested = False
        fake_proc = MagicMock()
        fake_proc.poll.return_value = 1  # Subprocess exited on node disconnection
        mon._proc = fake_proc

        with patch.object(mon, "get_default_sink_info", return_value=("alsa_output.pci-0000_04_00.6.analog-stereo", "Ryzen HD Audio")):
            mon.check_default_sink()
            self.assertTrue(mon._restart_requested)

    def test_restarting_recorder_terminates_old_process_without_duplicates(self):
        """Verify stopping recorder cleanly terminates, waits, and closes stdout."""
        mon = AudioLevelMonitor.__new__(AudioLevelMonitor)
        import threading
        mon._lock = threading.Lock()
        mon._running = True
        mon._restart_requested = False
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        mon._proc = fake_proc

        mon._stop_recorder()
        self.assertIsNone(mon._proc)
        fake_proc.terminate.assert_called_once()
        fake_proc.wait.assert_called_once()
        fake_proc.stdout.close.assert_called_once()

    def test_preventing_microphone_capture(self):
        """Verify accidental microphone capture ports are rejected and force retargeting."""
        mon = AudioLevelMonitor.__new__(AudioLevelMonitor)
        import threading
        mon._lock = threading.Lock()
        mon._running = True
        mon._current_sink_name = "bluez_output.A4:C1:39:AA:43:78"
        mon._restart_requested = False
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        mon._proc = fake_proc

        with patch.object(mon, "get_default_sink_info", return_value=("bluez_output.A4:C1:39:AA:43:78", "soundcore R60i NC")):
            with patch.object(mon, "get_recorder_sources", return_value={"bluez_input.A4:C1:39:AA:43:78:capture_MONO"}):
                mon.check_default_sink()
                self.assertTrue(mon._restart_requested)
                fake_proc.terminate.assert_called_once()

    def test_handling_unavailable_monitor_nodes(self):
        """Verify unavailable pw-record binary falls back smoothly without crashing."""
        with patch("notch.shutil.which", return_value=None):
            mon = AudioLevelMonitor()
            try:
                import time
                time.sleep(0.05)
                self.assertIn("fallback", mon.get_source_name().lower())
                self.assertEqual(len(mon.get_levels()), 3)
            finally:
                mon.stop()


class TestAudioVisualizerSignalAccuracy(unittest.TestCase):
    """Deterministic synthetic audio validation tests for 3-band audio visualizer."""

    def setUp(self):
        self.monitor = AudioLevelMonitor()

    def tearDown(self):
        self.monitor.stop()

    @staticmethod
    def _make_sine(freq: float, n: int = 256, amp: float = 12000.0, fs: float = 8000.0):
        return [int(amp * math.sin(2.0 * math.pi * freq * i / fs)) for i in range(n)]

    def test_silence_produces_resting_output(self):
        """1. Silence (zeros) decays to and remains at resting height [0.25, 0.25, 0.25]."""
        self.monitor.reset_filters()
        silence = [0] * 256
        for _ in range(30):
            lv = self.monitor.process_samples(silence, is_playing=True)
        for x in lv:
            self.assertAlmostEqual(x, 0.25, delta=0.01)

    def test_160hz_sine_predominantly_activates_bass_bar(self):
        """2. 160 Hz tone predominantly activates the bass bar (bar 0) over mid and treble."""
        self.monitor.reset_filters()
        samples = self._make_sine(160.0)
        for _ in range(25):
            lv = self.monitor.process_samples(samples, is_playing=True)
        self.assertGreater(lv[0], lv[1])
        self.assertGreater(lv[0], lv[2])
        self.assertGreaterEqual(lv[0], 0.75)

    def test_800hz_sine_predominantly_activates_mid_bar(self):
        """3. 800 Hz tone predominantly activates the mid bar (bar 1) over bass and treble."""
        self.monitor.reset_filters()
        samples = self._make_sine(800.0)
        for _ in range(25):
            lv = self.monitor.process_samples(samples, is_playing=True)
        self.assertGreater(lv[1], lv[0])
        self.assertGreater(lv[1], lv[2])
        self.assertGreaterEqual(lv[1], 0.75)

    def test_2400hz_sine_predominantly_activates_treble_bar(self):
        """4. 2400 Hz tone predominantly activates the treble bar (bar 2) over bass and mid."""
        self.monitor.reset_filters()
        samples = self._make_sine(2400.0)
        for _ in range(25):
            lv = self.monitor.process_samples(samples, is_playing=True)
        self.assertGreater(lv[2], lv[0])
        self.assertGreater(lv[2], lv[1])
        self.assertGreaterEqual(lv[2], 0.75)

    def test_mixed_frequencies_activate_corresponding_bars(self):
        """5. Mixed (160 Hz + 2400 Hz) activates bass and treble while mid remains suppressed."""
        self.monitor.reset_filters()
        s_bass = self._make_sine(160.0)
        s_treble = self._make_sine(2400.0)
        s_mix = [int(0.5 * (b + t)) for b, t in zip(s_bass, s_treble)]
        for _ in range(25):
            lv = self.monitor.process_samples(s_mix, is_playing=True)
        self.assertGreater(lv[0], lv[1])
        self.assertGreater(lv[2], lv[1])

    def test_low_frequency_sweep_responds_smoothly(self):
        """6. Low-frequency sweep (60 Hz to 250 Hz) maintains active bass bar (> 0.40)."""
        self.monitor.reset_filters()
        for freq in range(60, 260, 20):
            lv = self.monitor.process_samples(self._make_sine(freq), is_playing=True)
        self.assertGreater(lv[0], 0.40)

    def test_high_frequency_sweep_responds_smoothly(self):
        """7. High-frequency sweep (1800 Hz to 3400 Hz) maintains active treble bar (> 0.40)."""
        self.monitor.reset_filters()
        for freq in range(1800, 3400, 150):
            lv = self.monitor.process_samples(self._make_sine(freq), is_playing=True)
        self.assertGreater(lv[2], 0.40)

    def test_random_low_level_noise_rejected_at_resting_height(self):
        """8. Random low-level noise below noise floor stays at resting height without false movement."""
        import random
        self.monitor.reset_filters()
        random.seed(42)
        for _ in range(30):
            noise = [random.randint(-15, 15) for _ in range(256)]
            lv = self.monitor.process_samples(noise, is_playing=True)
        for x in lv:
            self.assertAlmostEqual(x, 0.25, delta=0.05)

    def test_full_scale_clipping_stability(self):
        """9. Full-scale clipping (+/-32767) remains strictly bounded in [0.0, 1.0] without NaN/inf."""
        self.monitor.reset_filters()
        s_clip = [32767 if (i // 20) % 2 == 0 else -32768 for i in range(256)]
        for _ in range(20):
            lv = self.monitor.process_samples(s_clip, is_playing=True)
        for x in lv:
            self.assertFalse(math.isnan(x))
            self.assertFalse(math.isinf(x))
            self.assertGreaterEqual(x, 0.0)
            self.assertLessEqual(x, 1.0)

    def test_sample_buffer_boundary_integrity(self):
        """10. Processing across chunk boundaries maintains continuous smooth output without glitching."""
        self.monitor.reset_filters()
        long_stream = self._make_sine(800.0, n=1024)
        c1 = long_stream[:256]
        c2 = long_stream[256:512]
        self.monitor.process_samples(c1, is_playing=True)
        lv2 = self.monitor.process_samples(c2, is_playing=True)
        self.assertFalse(math.isnan(lv2[1]))
        self.assertGreater(lv2[1], 0.5)


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
        """Verify manual override detection using an isolated temporary file without touching host state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            isolated_override = os.path.join(tmpdir, "dynamic_notch_cinema_override")
            controller = CinemaModeController()
            controller._override_file = isolated_override
            try:
                # With no override file present and X11 check mocked to False, check_fullscreen MUST be False
                with patch.object(controller, "_check_x11_fullscreen", return_value=False):
                    self.assertFalse(controller.check_fullscreen())

                # When the isolated override file is created, check_fullscreen MUST be True
                with open(isolated_override, "w") as f:
                    f.write("1\n")
                self.assertTrue(controller.check_fullscreen())
            finally:
                controller.close()

    def test_debounce_hysteresis_logic(self):
        """Verify production DynamicIslandWindow._check_cinema_mode debounce & hysteresis transitions."""
        win = MagicMock(spec=notch.DynamicIslandWindow)
        win._cinema = MagicMock()
        win._cinema_debounce_counter = 0
        win._is_cinema_suppressed = False
        win._enter_cinema_suppression = MagicMock()
        win._exit_cinema_suppression = MagicMock()

        # 1. Fullscreen detected: enters suppression immediately on tick 1
        win._cinema.check_fullscreen.return_value = True
        ret = notch.DynamicIslandWindow._check_cinema_mode(win)
        self.assertTrue(ret)
        self.assertEqual(win._cinema_debounce_counter, 1)
        win._enter_cinema_suppression.assert_called_once()
        win._exit_cinema_suppression.assert_not_called()

        # Simulate suppression active
        win._is_cinema_suppressed = True
        win._enter_cinema_suppression.reset_mock()

        # 2. Continuous fullscreen increments counter and caps at 3 without re-entering
        for _ in range(5):
            notch.DynamicIslandWindow._check_cinema_mode(win)
        self.assertEqual(win._cinema_debounce_counter, 3)
        win._enter_cinema_suppression.assert_not_called()
        win._exit_cinema_suppression.assert_not_called()

        # 3. Fullscreen exits: counter must decrement over 3 consecutive ticks before restoring
        win._cinema.check_fullscreen.return_value = False

        # Non-fullscreen tick 1: counter drops to 2, must not exit suppression
        notch.DynamicIslandWindow._check_cinema_mode(win)
        self.assertEqual(win._cinema_debounce_counter, 2)
        win._exit_cinema_suppression.assert_not_called()

        # Non-fullscreen tick 2: counter drops to 1, still suppressed
        notch.DynamicIslandWindow._check_cinema_mode(win)
        self.assertEqual(win._cinema_debounce_counter, 1)
        win._exit_cinema_suppression.assert_not_called()

        # Non-fullscreen tick 3: counter reaches 0, exits suppression
        notch.DynamicIslandWindow._check_cinema_mode(win)
        self.assertEqual(win._cinema_debounce_counter, 0)
        win._exit_cinema_suppression.assert_called_once()


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
        win._anim_target_h = float(notch.EXPANDED_H)
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

    def test_spring_curve_properties(self):
        """Verify critically damped spring curve: boundary, zero initial jerk, and monotonicity."""
        for is_exp in (True, False):
            steps = 50
            factors = [notch._anim_curve(i / float(steps), is_expanding=is_exp) for i in range(steps + 1)]
            self.assertAlmostEqual(factors[0], 0.0, places=6)
            self.assertAlmostEqual(factors[-1], 1.0, places=6)
            # Strictly monotonic
            for j in range(len(factors) - 1):
                self.assertGreater(factors[j + 1], factors[j])
            # Smooth takeoff: first step delta is gentle (smooth acceleration)
            self.assertLess(factors[1] - factors[0], 0.12)

    def test_expand_and_collapse_durations(self):
        """Verify separate duration assignment for expansion (~300ms) and collapse (~250ms)."""
        win = MagicMock(spec=notch.DynamicIslandWindow)
        win.STATE_IDLE = notch.DynamicIslandWindow.STATE_IDLE
        win.STATE_COMPACT = notch.DynamicIslandWindow.STATE_COMPACT
        win.STATE_FULL = notch.DynamicIslandWindow.STATE_FULL
        win.STATE_NOTIF = notch.DynamicIslandWindow.STATE_NOTIF
        win.STATE_EMPTY = notch.DynamicIslandWindow.STATE_EMPTY
        win.STATE_CINEMA_SUPPRESSED = notch.DynamicIslandWindow.STATE_CINEMA_SUPPRESSED
        win._is_cinema_suppressed = False
        win._idle_box = MagicMock()
        win._compact_box = MagicMock()
        win._notif_box = MagicMock()
        win._empty_box = MagicMock()
        win._full_box = MagicMock()
        win._has_lyrics = True

        # Test expand transition from compact (280x44) to full (400x178)
        win._current_w = 280.0
        win._current_h = 44.0
        win._anim_running = False
        win._state = notch.DynamicIslandWindow.STATE_COMPACT
        win._target_state = None
        notch.DynamicIslandWindow._animate_to(win, notch.DynamicIslandWindow.STATE_FULL)
        self.assertTrue(win._anim_is_expanding)
        self.assertEqual(win._anim_duration_ms, float(notch.ANIM_EXPAND_MS))

        # Test collapse transition from full (400x178) to compact (280x44)
        win._current_w = 400.0
        win._current_h = float(notch.EXPANDED_H)
        win._anim_running = False
        win._state = notch.DynamicIslandWindow.STATE_FULL
        win._target_state = None
        notch.DynamicIslandWindow._animate_to(win, notch.DynamicIslandWindow.STATE_COMPACT)
        self.assertFalse(win._anim_is_expanding)
        self.assertEqual(win._anim_duration_ms, float(notch.ANIM_COLLAPSE_MS))

    def test_cancel_timer_cleans_tick_callback(self):
        """Verify _cancel_timer removes both GLib timer and GTK tick callback without dangling sources."""
        from gi.repository import GLib

        real_source = GLib.timeout_add(10000, lambda: True)
        obj = MagicMock()
        obj._anim_running = True
        obj._anim_tick_id = 42
        obj._anim_timer = real_source

        notch.DynamicIslandWindow._cancel_timer(obj, "_anim_timer")
        self.assertFalse(obj._anim_running)
        self.assertIsNone(obj._anim_tick_id)
        self.assertIsNone(obj._anim_timer)
        obj.remove_tick_callback.assert_called_once_with(42)


class TestLyricLayoutPresentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from gi.repository import Gtk
        Gtk.init_check(None)

    def setUp(self):
        self.win = notch.DynamicIslandWindow()

    def test_expanded_h_target_and_constants(self):
        """Verify EXPANDED_H is within the design range and compact/nolyric targets are preserved."""
        self.assertEqual(notch.EXPANDED_H, 178)
        self.assertTrue(155 <= notch.EXPANDED_H <= 185)
        self.assertEqual(notch.COMPACT_W, 280)
        self.assertEqual(notch.COMPACT_H, 44)
        self.assertEqual(notch.EXPANDED_H_NOLYRIC, 146)

    def test_lyric_label_configuration(self):
        """Verify the 2-line wrapping, word-char wrap mode, fill alignment, and bounded max chars on _full_lyric_label."""
        from gi.repository import Pango, Gtk
        lbl = self.win._full_lyric_label
        self.assertTrue(lbl.get_line_wrap())
        self.assertEqual(lbl.get_line_wrap_mode(), Pango.WrapMode.WORD_CHAR)
        self.assertEqual(lbl.get_lines(), 2)
        self.assertEqual(lbl.get_ellipsize(), Pango.EllipsizeMode.END)
        self.assertEqual(lbl.get_halign(), Gtk.Align.FILL)
        self.assertTrue(lbl.get_hexpand())
        self.assertEqual(lbl.get_xalign(), 0.0)
        self.assertEqual(lbl.get_max_width_chars(), 42)

    def test_lyric_row_height_stability_across_line_counts(self):
        """Verify that _lyric_row reserves 36px so layout does not jump between 1 and 2 lines."""
        self.win.show_all()
        row = self.win._lyric_row
        lbl = self.win._full_lyric_label

        # Size request must be explicitly 36px
        self.assertEqual(row.get_size_request()[1], 36)

        texts = [
            "",
            "“Is this the real life?”",
            "“Is this the real life? Is this just fantasy? Caught in a landslide, no escape from reality”",
            "“Mama, just killed a man, put a gun against his head, pulled my trigger, now he is dead. Mama, life had just begun, but now I have gone and thrown it all away”"
        ]

        for text in texts:
            lbl.set_text(text)
            self.win.check_resize()
            min_h, nat_h = row.get_preferred_height_for_width(360)
            self.assertEqual(min_h, 36, f"Row min height should be 36 for text '{text[:20]}', got {min_h}")
            self.assertEqual(nat_h, 36, f"Row nat height should be 36 for text '{text[:20]}', got {nat_h}")

    def test_expanded_lyrics_realized_allocation_and_two_line_limit(self):
        """Verify expanded lyrics layout across varied string inputs in realized GTK window.
        Tests:
        1. Short lyric (fits on 1 line).
        2. Lyric containing a natural line break (2 lines).
        3. Long lyric exceeding two lines (wraps and ellipsizes).
        4. Extremely long lyric (500+ characters).
        5. Unicode lyric text (Japanese / emoji).
        6. A single extremely long word without spaces (Pango.WrapMode.WORD_CHAR fallback).
        Confirms:
        - Lyric widget never exceeds parent allocation (<= 360 px).
        - Visible line count never exceeds 2 lines.
        - Reserved lyric row remains strictly 36 px.
        - Expanded geometry remains strictly 400 x 178.
        """
        self.win.show_all()
        alloc = notch.Gdk.Rectangle()
        alloc.width = 440
        alloc.height = 250

        cases = [
            ("Short lyric", 1),
            ("Line 1\nLine 2", 2),
            ("This is a longer line of synchronized lyrics that naturally wraps across two lines on the expanded player", 2),
            ("An excessively long synchronized lyric line that contains dozens of words and extends far beyond two full lines so it must wrap on the first line and then continue and ellipsize at the end of the second line", 2),
            ("日本語の歌詞テスト 🎶 🎧 日本語の歌詞テスト 🚀 日本語の歌詞テスト ✨ 日本語の歌詞テスト", 2),
            ("SupercalifragilisticexpialidociousSupercalifragilisticexpialidociousSupercalifragilisticexpialidocious", 2),
            ("W" * 550, 2),
        ]

        for lyric_text, exp_max_lines in cases:
            parts = lyric_text.replace("\r", "").split("\n")
            if len(parts) > 2:
                norm_lyric = parts[0] + "\n" + " ".join(parts[1:])
            else:
                norm_lyric = lyric_text

            self.win._full_lyric_label.set_text(norm_lyric)
            self.win._lyric_row.set_visible(True)
            self.win._full_box.set_size_request(notch.EXPANDED_W, notch.EXPANDED_H)
            self.win._overlay.size_allocate(alloc)

            fb_alloc = self.win._full_box.get_allocation()
            row_alloc = self.win._lyric_row.get_allocation()
            lyric_alloc = self.win._full_lyric_label.get_allocation()
            layout = self.win._full_lyric_label.get_layout()
            lines = layout.get_line_count()

            self.assertEqual(fb_alloc.width, notch.EXPANDED_W, f"full_box width must be {notch.EXPANDED_W} for '{lyric_text[:20]}', got {fb_alloc.width}")
            self.assertEqual(fb_alloc.height, notch.EXPANDED_H, f"full_box height must be {notch.EXPANDED_H} for '{lyric_text[:20]}', got {fb_alloc.height}")
            self.assertEqual(row_alloc.height, 36, f"lyric_row height must be 36 for '{lyric_text[:20]}', got {row_alloc.height}")
            self.assertLessEqual(lyric_alloc.width, 360, f"lyric label width must not exceed 360 for '{lyric_text[:20]}', got {lyric_alloc.width}")
            self.assertLessEqual(lines, 2, f"lyric lines must be <= 2 for '{lyric_text[:20]}', got {lines}")

            # Natural width request of full_box must never exceed EXPANDED_W = 400
            _min_w, nat_w = self.win._full_box.get_preferred_width()
            self.assertLessEqual(nat_w, notch.EXPANDED_W)


class TestBluetoothBatteryLifecycle(unittest.TestCase):
    def setUp(self):
        # Create an isolated instance with mock bus to avoid host state interference
        with patch("dbus.SystemBus"):
            self.bt = notch.BluetoothBattery()
            self.bt._bus = MagicMock()

    def tearDown(self):
        self.bt.close()

    def test_device_name_alias_preference(self):
        """Verify org.bluez.Device1.Alias is preferred over Name."""
        dev = {"Alias": "Sony WH-1000XM4 (Leon)", "Name": "WH-1000XM4"}
        name = self.bt._get_device_display_name(dev)
        self.assertEqual(name, "Sony WH-1000XM4 (Leon)")

    def test_device_name_fallback_to_name(self):
        """Verify fallback to Name when Alias is missing or empty."""
        dev = {"Name": "AirPods Pro"}
        name = self.bt._get_device_display_name(dev)
        self.assertEqual(name, "AirPods Pro")

    def test_device_name_mac_address_suppressed(self):
        """Verify raw MAC addresses and dev_ paths are never displayed to the user."""
        dev_mac = {"Alias": "A4:C1:39:AA:43:78", "Name": "A4-C1-39-AA-43-78"}
        self.assertEqual(self.bt._get_device_display_name(dev_mac), "Bluetooth Headset")

        dev_path = {"Alias": "dev_A4_C1_39_AA_43_78"}
        self.assertEqual(self.bt._get_device_display_name(dev_path), "Bluetooth Headset")

    def test_audio_device_classification(self):
        """Verify audio headsets are recognized via Icon, Class (CoD), or UUIDs, while rejecting non-audio."""
        # Headset icon
        self.assertTrue(self.bt._is_audio_device({"Icon": "audio-headset"}))
        self.assertTrue(self.bt._is_audio_device({"Icon": "audio-headphones"}))

        # Audio/Video Class of Device (0x240404)
        self.assertTrue(self.bt._is_audio_device({"Class": 2360324}))

        # A2DP Sink UUID
        self.assertTrue(self.bt._is_audio_device({"UUIDs": ["0000110b-0000-1000-8000-00805f9b34fb"]}))

        # Non-audio device (mouse)
        mouse = {"Icon": "input-mouse", "Class": 960, "UUIDs": ["00001812-0000-1000-8000-00805f9b34fb"]}
        self.assertFalse(self.bt._is_audio_device(mouse))

    def test_connected_and_disconnected_filtering(self):
        """Verify only connected audio devices are tracked."""
        objs = {
            "/org/bluez/hci0/dev_11": {
                "org.bluez.Device1": {"Alias": "Headset 1", "Connected": True, "Icon": "audio-headset"}
            },
            "/org/bluez/hci0/dev_22": {
                "org.bluez.Device1": {"Alias": "Headset 2", "Connected": False, "Icon": "audio-headset"}
            }
        }
        res = self.bt._refresh_headsets_from_objects(objs)
        self.assertIn("/org/bluez/hci0/dev_11", res)
        self.assertNotIn("/org/bluez/hci0/dev_22", res)
        self.assertEqual(res["/org/bluez/hci0/dev_11"]["name"], "Headset 1")

    def test_aggregate_battery_percentage(self):
        """Verify single aggregate battery percentage extraction."""
        objs = {
            "/org/bluez/hci0/dev_11": {
                "org.bluez.Device1": {"Alias": "Soundcore", "Connected": True, "Icon": "audio-headset"},
                "org.bluez.Battery1": {"Percentage": 85, "Source": "HFP"}
            }
        }
        pct, text, comps = self.bt._extract_battery("/org/bluez/hci0/dev_11", objs)
        self.assertEqual(pct, 85)
        self.assertEqual(text, "85%")
        self.assertEqual(comps, {})

    def test_missing_battery1_interface(self):
        """Verify device without Battery1 reports None and 'Battery unavailable' (never 0% or -1)."""
        objs = {
            "/org/bluez/hci0/dev_11": {
                "org.bluez.Device1": {"Alias": "Bose QC35", "Connected": True, "Icon": "audio-headphones"}
            }
        }
        pct, text, comps = self.bt._extract_battery("/org/bluez/hci0/dev_11", objs)
        self.assertIsNone(pct)
        self.assertEqual(text, "Battery unavailable")

    def test_missing_percentage_property(self):
        """Verify device with Battery1 but missing Percentage property handles safely."""
        objs = {
            "/org/bluez/hci0/dev_11": {
                "org.bluez.Device1": {"Alias": "Headset", "Connected": True, "Icon": "audio-headset"},
                "org.bluez.Battery1": {"Source": "GATT"}  # No Percentage
            }
        }
        pct, text, comps = self.bt._extract_battery("/org/bluez/hci0/dev_11", objs)
        self.assertIsNone(pct)
        self.assertEqual(text, "Battery unavailable")

    def test_multiple_battery_components_identifier(self):
        """Verify multi-component TWS battery extraction using the Identifier property."""
        objs = {
            "/org/bluez/hci0/dev_11": {
                "org.bluez.Device1": {"Alias": "Pixel Buds Pro", "Connected": True, "Icon": "audio-headset"}
            },
            "/org/bluez/hci0/dev_11/battery0": {
                "org.bluez.Battery1": {"Identifier": "left", "Percentage": 80}
            },
            "/org/bluez/hci0/dev_11/battery1": {
                "org.bluez.Battery1": {"Identifier": "right", "Percentage": 75}
            },
            "/org/bluez/hci0/dev_11/battery2": {
                "org.bluez.Battery1": {"Identifier": "case", "Percentage": 90}
            }
        }
        pct, text, comps = self.bt._extract_battery("/org/bluez/hci0/dev_11", objs)
        self.assertEqual(text, "L: 80% · R: 75% · Case: 90%")
        self.assertEqual(comps["left"]["percent"], 80)
        self.assertEqual(comps["right"]["percent"], 75)
        self.assertEqual(comps["case"]["percent"], 90)

    def test_battery_percentage_property_updates(self):
        """Verify PropertiesChanged on Battery1 updates battery state and notifies callback."""
        callback = MagicMock()
        self.bt._on_change_callback = callback
        dev_path = "/org/bluez/hci0/dev_11"
        self.bt._connected_headsets = {
            dev_path: {
                "name": "Headset", "percent": 80, "battery_text": "80%", "components": {},
                "is_laptop": False, "connected": True, "path": dev_path
            }
        }

        # Mock _refresh_headsets to return updated battery
        updated_dict = {
            dev_path: {
                "name": "Headset", "percent": 70, "battery_text": "70%", "components": {},
                "is_laptop": False, "connected": True, "path": dev_path
            }
        }
        with patch.object(self.bt, "_refresh_headsets", return_value=updated_dict):
            self.bt._on_properties_changed("org.bluez.Battery1", {"Percentage": 70}, [], path=dev_path)

        callback.assert_called_with("battery_changed", updated_dict[dev_path])

    def test_low_battery_notification_trigger(self):
        """Verify battery dropping to <= 20% dispatches low_battery event."""
        callback = MagicMock()
        self.bt._on_change_callback = callback
        dev_path = "/org/bluez/hci0/dev_11"
        self.bt._connected_headsets = {
            dev_path: {
                "name": "Headset", "percent": 80, "battery_text": "80%", "components": {},
                "is_laptop": False, "connected": True, "path": dev_path
            }
        }

        low_dict = {
            dev_path: {
                "name": "Headset", "percent": 15, "battery_text": "15%", "components": {},
                "is_laptop": False, "connected": True, "path": dev_path
            }
        }
        with patch.object(self.bt, "_refresh_headsets", return_value=low_dict):
            self.bt._on_properties_changed("org.bluez.Battery1", {"Percentage": 15}, [], path=dev_path)

        # Must have dispatched both battery_changed and low_battery
        callback.assert_any_call("battery_changed", low_dict[dev_path])
        callback.assert_any_call("low_battery", low_dict[dev_path])
        self.assertIn(dev_path, self.bt._notified_low_batteries)

    def test_device_connection_and_disconnection_signals(self):
        """Verify device connection and disconnection signals dispatch proper events."""
        callback = MagicMock()
        self.bt._on_change_callback = callback
        dev_path = "/org/bluez/hci0/dev_11"

        # 1. Connection signal
        headset_dict = {
            dev_path: {
                "name": "New Buds", "percent": 100, "battery_text": "100%", "components": {},
                "is_laptop": False, "connected": True, "path": dev_path
            }
        }
        with patch.object(self.bt, "_refresh_headsets", return_value=headset_dict):
            self.bt._on_properties_changed("org.bluez.Device1", {"Connected": True}, [], path=dev_path)
        callback.assert_called_with("connected", headset_dict[dev_path])

        # 2. Disconnection signal
        callback.reset_mock()
        self.bt._connected_headsets = dict(headset_dict)
        self.bt._on_properties_changed("org.bluez.Device1", {"Connected": False}, [], path=dev_path)
        callback.assert_called_with("disconnected", headset_dict[dev_path])
        self.assertNotIn(dev_path, self.bt._connected_headsets)

    def test_missing_bluez_service_graceful_fallback(self):
        """Verify missing BlueZ service or D-Bus failure does not raise exceptions."""
        with patch("dbus.SystemBus", side_effect=Exception("D-Bus daemon down")):
            bt = notch.BluetoothBattery()
            self.assertIsNone(bt._bus)
            # Must safely fall back without crash
            headset = bt.get_headset_info()
            self.assertIsNone(headset)

    def test_clean_application_shutdown(self):
        """Verify close() removes all registered D-Bus signal matches."""
        m1 = MagicMock()
        m2 = MagicMock()
        self.bt._signal_matches = [m1, m2]
        self.bt._connected_headsets = {"/dev": {}}

        self.bt.close()
        m1.remove.assert_called_once()
        m2.remove.assert_called_once()
        self.assertEqual(len(self.bt._signal_matches), 0)
        self.assertEqual(len(self.bt._connected_headsets), 0)

    def test_interfaces_added_avoids_path_collision_and_processes_payload_path(self):
        """Verify _on_interfaces_added accepts positional object_path and keyword signal_path without TypeError."""
        callback = MagicMock()
        self.bt._on_change_callback = callback
        dev_path = "/org/bluez/hci0/dev_22_33_44_55_66_77"
        signal_emitter_path = "/"

        headset_info = {
            "name": "Noise Cancelling Headphones",
            "percent": 90,
            "battery_text": "90%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": dev_path
        }

        with patch.object(self.bt, "_refresh_headsets", return_value={dev_path: headset_info}):
            # dbus-python passes positional args (object_path, interfaces) and keyword signal_path
            try:
                self.bt._on_interfaces_added(
                    dev_path,
                    {"org.bluez.Device1": {"Connected": True}},
                    signal_path=signal_emitter_path
                )
            except TypeError as exc:
                self.fail(f"_on_interfaces_added raised TypeError on dbus-python kwargs: {exc}")

        # Verified payload object_path was processed, and emitter signal_path was not mistaken for device path
        callback.assert_called_once_with("connected", headset_info)
        self.assertNotIn(signal_emitter_path, self.bt._connected_headsets)

    def test_interfaces_added_battery_interface_detection(self):
        """Verify newly exposed Battery1 interface on child path updates battery state."""
        callback = MagicMock()
        self.bt._on_change_callback = callback
        dev_path = "/org/bluez/hci0/dev_AA_BB_CC"
        battery_path = f"{dev_path}/battery1"
        signal_emitter_path = "/"

        # Pre-populate device without battery
        self.bt._connected_headsets = {
            dev_path: {
                "name": "Wireless Buds",
                "percent": None,
                "battery_text": "Battery unavailable",
                "components": {},
                "is_laptop": False,
                "connected": True,
                "path": dev_path
            }
        }

        updated_info = {
            "name": "Wireless Buds",
            "percent": 85,
            "battery_text": "85%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": dev_path
        }

        with patch.object(self.bt, "_refresh_headsets", return_value={dev_path: updated_info}):
            # Battery1 interface added under child object path
            self.bt._on_interfaces_added(
                battery_path,
                {"org.bluez.Battery1": {"Percentage": 85}},
                signal_path=signal_emitter_path
            )

        callback.assert_called_once_with("battery_changed", updated_info)

    def test_interfaces_removed_avoids_path_collision(self):
        """Verify _on_interfaces_removed handles positional object_path and keyword signal_path without collision."""
        callback = MagicMock()
        self.bt._on_change_callback = callback
        dev_path = "/org/bluez/hci0/dev_99_88_77"
        signal_emitter_path = "/"

        headset_info = {
            "name": "Sport Buds",
            "percent": 50,
            "battery_text": "50%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": dev_path
        }
        self.bt._connected_headsets = {dev_path: headset_info}
        self.bt._notified_low_batteries.add(dev_path)

        try:
            self.bt._on_interfaces_removed(
                dev_path,
                ["org.bluez.Device1"],
                signal_path=signal_emitter_path
            )
        except TypeError as exc:
            self.fail(f"_on_interfaces_removed raised TypeError on dbus-python kwargs: {exc}")

        callback.assert_called_once_with("disconnected", headset_info)
        self.assertNotIn(dev_path, self.bt._connected_headsets)
        self.assertNotIn(dev_path, self.bt._notified_low_batteries)
        self.assertNotIn(signal_emitter_path, self.bt._connected_headsets)

    def test_signal_receiver_registration_options(self):
        """Verify signal receivers use unambiguous path_keyword='signal_path' for ObjectManager signals."""
        mock_bus = MagicMock()
        bt = notch.BluetoothBattery.__new__(notch.BluetoothBattery)
        bt._bus = mock_bus
        bt._signal_matches = []
        bt._connected_headsets = {}
        bt._notified_low_batteries = set()
        bt._on_change_callback = None

        bt._setup_signals()

        # Find calls for InterfacesAdded and InterfacesRemoved
        signal_calls = mock_bus.add_signal_receiver.call_args_list
        interfaces_added_call = None
        interfaces_removed_call = None

        for c in signal_calls:
            kwargs = c.kwargs
            if kwargs.get("signal_name") == "InterfacesAdded":
                interfaces_added_call = kwargs
            elif kwargs.get("signal_name") == "InterfacesRemoved":
                interfaces_removed_call = kwargs

        self.assertIsNotNone(interfaces_added_call, "InterfacesAdded receiver must be registered")
        self.assertEqual(
            interfaces_added_call.get("path_keyword"),
            "signal_path",
            "InterfacesAdded must use path_keyword='signal_path' to avoid collision with positional object_path"
        )

        self.assertIsNotNone(interfaces_removed_call, "InterfacesRemoved receiver must be registered")
        self.assertEqual(
            interfaces_removed_call.get("path_keyword"),
            "signal_path",
            "InterfacesRemoved must use path_keyword='signal_path' to avoid collision with positional object_path"
        )


class TestPersistentBluetoothUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from gi.repository import Gtk
        Gtk.init_check(None)

    def setUp(self):
        self.win = notch.DynamicIslandWindow()

    def tearDown(self):
        self.win._on_delete()
        self.win.destroy()

    def test_compact_mode_does_not_allocate_space_for_bluetooth_battery_label(self):
        """Verify compact mode layout has no Bluetooth battery widget and does not consume horizontal space."""
        # 1. Verify compact box does not contain compact_bt_label
        self.assertFalse(hasattr(self.win, "compact_bt_label"), "compact_bt_label attribute should be removed")
        children = self.win._compact_box.get_children()

        # Children must be strictly: [art_container, info_col, activity_indicator]
        self.assertEqual(len(children), 3)
        self.assertEqual(children[0], self.win.compact_art_container)
        self.assertEqual(children[2], self.win.compact_activity)

        # 2. Connect a headset and verify compact box children remain untouched
        info = {
            "name": "soundcore R60i NC",
            "percent": 90,
            "battery_text": "90%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": "/org/bluez/hci0/dev_11"
        }
        self.win._update_persistent_bt(info)
        post_children = self.win._compact_box.get_children()
        self.assertEqual(len(post_children), 3)

        # Ensure no child label in compact_box displays Bluetooth battery info
        for child in post_children:
            if hasattr(child, "get_text"):
                self.assertNotIn("🎧", child.get_text())
                self.assertNotIn("90%", child.get_text())

    def test_original_compact_dimensions_remain_unchanged(self):
        """Verify original compact dimensions (280x44) and internal element geometries are preserved."""
        self.assertEqual(notch.COMPACT_W, 280)
        self.assertEqual(notch.COMPACT_H, 44)
        self.assertEqual(self.win._compact_box.get_size_request(), (280, 44))
        self.assertEqual(self.win.compact_art_container.get_size_request(), (notch.ART_SIZE_COMPACT, notch.ART_SIZE_COMPACT))

    def test_connected_headset_stored_in_persistent_state(self):
        """Verify connected headset info is stored in self.win._persistent_bt_device."""
        info = {
            "name": "soundcore R60i NC",
            "percent": 90,
            "battery_text": "90%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": "/org/bluez/hci0/dev_11"
        }
        self.win._on_bt_event("connected", info)
        self.assertIsNotNone(self.win._persistent_bt_device)
        self.assertEqual(self.win._persistent_bt_device["name"], "soundcore R60i NC")
        self.assertEqual(self.win._persistent_bt_device["percent"], 90)

    def test_expanded_mode_displays_headset_name_and_battery(self):
        """Verify expanded player presents headset name and battery level persistently."""
        info = {
            "name": "soundcore R60i NC",
            "percent": 90,
            "battery_text": "90%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": "/org/bluez/hci0/dev_11"
        }
        self.win._update_persistent_bt(info)
        self.assertTrue(self.win.full_bt_box.get_visible())
        self.assertEqual(self.win.full_bt_name.get_text(), "🎧 soundcore R60i NC")
        self.assertEqual(self.win.full_bt_battery.get_text(), "Battery 90%")

    def test_expanded_status_survives_transient_notification_dismissal(self):
        """Verify dismissing a transient notification does not clear persistent headset status."""
        info = {
            "name": "soundcore R60i NC",
            "percent": 90,
            "battery_text": "90%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": "/org/bluez/hci0/dev_11"
        }
        self.win._on_bt_event("connected", info)
        self.assertEqual(self.win._target_state, self.win.STATE_NOTIF)

        # Notification timer expires and dismisses notification
        self.win._dismiss_notification()

        # State transitions back, but persistent state remains intact in expanded UI
        self.assertIsNotNone(self.win._persistent_bt_device)
        self.assertEqual(self.win._persistent_bt_device["name"], "soundcore R60i NC")
        self.assertTrue(self.win.full_bt_box.get_visible())
        self.assertEqual(self.win.full_bt_name.get_text(), "🎧 soundcore R60i NC")
        self.assertEqual(self.win.full_bt_battery.get_text(), "Battery 90%")

    def test_battery_updates_refresh_expanded_status(self):
        """Verify battery percentage updates refresh persistent state and expanded labels."""
        info = {
            "name": "AirPods Pro",
            "percent": 90,
            "battery_text": "90%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": "/org/bluez/hci0/dev_33"
        }
        self.win._update_persistent_bt(info)
        self.assertEqual(self.win.full_bt_battery.get_text(), "Battery 90%")

        # Battery level changes to 80%
        info_updated = dict(info)
        info_updated["percent"] = 80
        info_updated["battery_text"] = "80%"

        self.win._on_bt_event("battery_changed", info_updated)
        self.assertEqual(self.win._persistent_bt_device["percent"], 80)
        self.assertEqual(self.win.full_bt_battery.get_text(), "Battery 80%")

    def test_missing_battery_information_retains_headset_name(self):
        """Verify missing battery info displays headset name and 'Battery unavailable' (never 0% or -1)."""
        info = {
            "name": "Sony WH-1000XM4",
            "percent": None,
            "battery_text": "Battery unavailable",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": "/org/bluez/hci0/dev_44"
        }
        self.win._update_persistent_bt(info)
        self.assertEqual(self.win.full_bt_name.get_text(), "🎧 Sony WH-1000XM4")
        self.assertEqual(self.win.full_bt_battery.get_text(), "Battery unavailable")

    def test_disconnect_clears_persistent_bluetooth_status(self):
        """Verify device disconnection clears persistent state and hides Bluetooth indicators."""
        info = {
            "name": "Pixel Buds",
            "percent": 75,
            "battery_text": "75%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": "/org/bluez/hci0/dev_55"
        }
        self.win._update_persistent_bt(info)
        self.assertTrue(self.win.full_bt_box.get_visible())

        self.win._on_bt_event("disconnected", info)
        self.assertIsNone(self.win._persistent_bt_device)
        self.assertFalse(self.win.full_bt_box.get_visible())
        self.assertFalse(self.win.empty_bt_label.get_visible())

    def test_reconnection_restores_status(self):
        """Verify reconnecting restores persistent state and unhides expanded indicators."""
        info = {
            "name": "Pixel Buds",
            "percent": 75,
            "battery_text": "75%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": "/org/bluez/hci0/dev_55"
        }
        self.win._update_persistent_bt(info)
        self.win._on_bt_event("disconnected", info)
        self.assertIsNone(self.win._persistent_bt_device)

        self.win._on_bt_event("connected", info)
        self.assertIsNotNone(self.win._persistent_bt_device)
        self.assertTrue(self.win.full_bt_box.get_visible())
        self.assertEqual(self.win.full_bt_name.get_text(), "🎧 Pixel Buds")
        self.assertEqual(self.win.full_bt_battery.get_text(), "Battery 75%")

    def test_empty_expanded_state_provides_access_to_headset_info(self):
        """Verify idle/empty expanded state provides access to connected headset info."""
        info = {
            "name": "soundcore R60i NC",
            "percent": 90,
            "battery_text": "90%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": "/org/bluez/hci0/dev_11"
        }
        self.win._update_persistent_bt(info)
        self.assertTrue(self.win.empty_bt_label.get_visible())
        self.assertEqual(self.win.empty_bt_label.get_text(), "🎧 soundcore R60i NC · Battery 90%")

    def test_headset_connected_before_startup_detected_and_displayed(self):
        """Verify headset connected prior to launch is detected and shown in expanded state."""
        info = {
            "name": "JBL Live",
            "percent": 95,
            "battery_text": "95%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": "/org/bluez/hci0/dev_66"
        }
        with patch.object(self.win.bt, "get_headset_info", return_value=info):
            self.win._check_initial_headset()

        self.assertIsNotNone(self.win._persistent_bt_device)
        self.assertEqual(self.win._persistent_bt_device["name"], "JBL Live")
        self.assertEqual(self.win.full_bt_name.get_text(), "🎧 JBL Live")
        self.assertEqual(self.win.full_bt_battery.get_text(), "Battery 95%")

    def test_low_battery_notifications_do_not_clear_persistent_state(self):
        """Verify firing low-battery event dispatches notification without clearing persistent state."""
        info = {
            "name": "Bose QC45",
            "percent": 15,
            "battery_text": "15%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": "/org/bluez/hci0/dev_77"
        }
        self.win._update_persistent_bt(info)
        self.win._on_bt_event("low_battery", info)
        self.assertIsNotNone(self.win._persistent_bt_device)
        self.assertEqual(self.win.full_bt_battery.get_text(), "Battery 15%")
        self.assertTrue(self.win.full_bt_box.get_visible())

    def test_multiple_connected_devices_handled_deterministically(self):
        """Verify multiple connected headsets maintain a stable primary headset deterministically."""
        bt = notch.BluetoothBattery.__new__(notch.BluetoothBattery)
        bt._signal_matches = []
        bt._notified_low_batteries = set()
        bt._primary_headset_path = None
        bt._on_change_callback = None

        dev_a = {"name": "Device A", "connected": True, "path": "/org/bluez/hci0/dev_AA", "percent": 50}
        dev_b = {"name": "Device B", "connected": True, "path": "/org/bluez/hci0/dev_BB", "percent": 60}
        bt._connected_headsets = {
            "/org/bluez/hci0/dev_BB": dev_b,
            "/org/bluez/hci0/dev_AA": dev_a
        }

        # First call selects deterministically (sorted key: dev_AA)
        primary1 = bt.get_headset_info()
        self.assertEqual(primary1["name"], "Device A")
        self.assertEqual(bt._primary_headset_path, "/org/bluez/hci0/dev_AA")

        # Successive calls remain latched to primary device without bouncing
        primary2 = bt.get_headset_info()
        self.assertEqual(primary2["name"], "Device A")

        # When primary device disconnects, it switches deterministically to remaining device
        del bt._connected_headsets["/org/bluez/hci0/dev_AA"]
        primary3 = bt.get_headset_info()
        self.assertEqual(primary3["name"], "Device B")
        self.assertEqual(bt._primary_headset_path, "/org/bluez/hci0/dev_BB")

    def test_bluez_restart_does_not_leave_stale_headset_data(self):
        """Verify BlueZ daemon restart clears stale headset data and restores upon re-emergence."""
        callback = MagicMock()
        self.win.bt._on_change_callback = callback
        self.win.bt._connected_headsets = {
            "/org/bluez/hci0/dev_11": {"name": "Headset", "connected": True, "path": "/org/bluez/hci0/dev_11"}
        }
        self.win.bt._primary_headset_path = "/org/bluez/hci0/dev_11"

        # BlueZ disappears
        self.win.bt._on_name_owner_changed("org.bluez", ":1.100", "")
        self.assertEqual(len(self.win.bt._connected_headsets), 0)
        self.assertIsNone(self.win.bt._primary_headset_path)
        callback.assert_called_with("disconnected", {"name": "Bluetooth Headset"})

        # BlueZ reappears with refreshed headset
        callback.reset_mock()
        new_headset = {
            "name": "Restored Headset",
            "percent": 90,
            "battery_text": "90%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": "/org/bluez/hci0/dev_11"
        }
        with patch.object(self.win.bt, "_refresh_headsets", return_value={"/org/bluez/hci0/dev_11": new_headset}):
            self.win.bt._on_name_owner_changed("org.bluez", "", ":1.200")

        callback.assert_called_with("connected", new_headset)

    def test_application_shutdown_cleans_up_signals_and_callbacks(self):
        """Verify shutdown cleanly closes Bluetooth matches and stops timers."""
        mock_close = MagicMock()
        self.win.bt.close = mock_close
        self.win._on_delete()
        mock_close.assert_called_once()
        self.assertIsNone(self.win._tick_timer)


class TestCompactSongTitleLayout(unittest.TestCase):
    """Test suite validating compact title label constraints and GTK size allocations."""

    def setUp(self):
        self.win = notch.DynamicIslandWindow()

    def tearDown(self):
        self.win._on_delete()
        self.win.destroy()

    def test_long_title_uses_single_line_ellipsization(self):
        """Verify long title labels enforce single-line mode and end-ellipsization."""
        self.assertTrue(self.win.compact_title.get_single_line_mode())
        self.assertFalse(self.win.compact_title.get_line_wrap())
        self.assertEqual(self.win.compact_title.get_ellipsize(), notch.Pango.EllipsizeMode.END)

        self.win.show_all()
        self.win.compact_title.set_text("Very Long Song Title That Exceeds Compact Pill Allocation By Far")
        alloc = notch.Gdk.Rectangle()
        alloc.width = 440
        alloc.height = 250
        self.win._overlay.size_allocate(alloc)

        layout = self.win.compact_title.get_layout()
        self.assertEqual(layout.get_line_count(), 1)
        self.assertTrue(layout.is_ellipsized())

    def test_title_does_not_force_excessive_natural_width(self):
        """Verify title labels do not force the compact container to request excessive natural width."""
        self.win.show_all()

        long_title = "A" * 300
        info = {"title": long_title, "artist": "Artist", "status": "Playing"}
        self.win._last_info = info
        self.win._update_compact_ui()

        # Allocate compact window dimensions
        alloc = notch.Gdk.Rectangle()
        alloc.x = 0
        alloc.y = 0
        alloc.width = 440
        alloc.height = 250
        self.win._overlay.size_allocate(alloc)

        # 1. Compact container geometry remains strictly 280x44
        box_alloc = self.win._compact_box.get_allocation()
        self.assertEqual(box_alloc.width, notch.COMPACT_W)
        self.assertEqual(box_alloc.height, notch.COMPACT_H)

        # 2. Preferred natural width is constrained to available geometry
        _min_w, nat_w = self.win._compact_box.get_preferred_width()
        self.assertLessEqual(nat_w, notch.COMPACT_W)

        # 3. Title uses single-line end ellipsization
        self.assertTrue(self.win.compact_title.get_single_line_mode())
        self.assertFalse(self.win.compact_title.get_line_wrap())
        self.assertEqual(self.win.compact_title.get_ellipsize(), notch.Pango.EllipsizeMode.END)
        layout = self.win.compact_title.get_layout()
        self.assertEqual(layout.get_line_count(), 1)
        self.assertTrue(layout.is_ellipsized())

        # 4. Metadata column and label allocations receive correct space
        col_alloc = self.win.compact_title.get_parent().get_allocation()
        title_alloc = self.win.compact_title.get_allocation()
        self.assertEqual(col_alloc.width, 196)
        self.assertEqual(title_alloc.width, col_alloc.width)
        self.assertTrue(self.win.compact_title.get_hexpand())
        self.assertEqual(self.win.compact_title.get_halign(), notch.Gtk.Align.FILL)
        self.assertEqual(self.win.compact_title.get_xalign(), 0.0)
        self.assertGreater(self.win.compact_title.get_max_width_chars(), 0)
        self.assertLessEqual(self.win.compact_title.get_max_width_chars(), 24)

        # 5. Artwork and equalizer remain inside the compact layout
        art_alloc = self.win.compact_art_container.get_allocation()
        act_alloc = self.win.compact_activity.get_allocation()
        self.assertGreaterEqual(art_alloc.x, 0)
        self.assertLessEqual(art_alloc.x + art_alloc.width, title_alloc.x)
        self.assertLessEqual(title_alloc.x + title_alloc.width, act_alloc.x)
        self.assertLessEqual(act_alloc.x + act_alloc.width, notch.COMPACT_W)

    def test_artist_label_remains_inside_allocated_area(self):
        """Verify artist label occupies predictable space and does not displace the title label."""
        self.assertTrue(self.win.compact_artist.get_single_line_mode())
        self.assertFalse(self.win.compact_artist.get_line_wrap())
        self.assertEqual(self.win.compact_artist.get_ellipsize(), notch.Pango.EllipsizeMode.END)
        self.assertTrue(self.win.compact_artist.get_hexpand())
        self.assertEqual(self.win.compact_artist.get_halign(), notch.Gtk.Align.FILL)
        self.assertEqual(self.win.compact_artist.get_xalign(), 0.0)
        self.assertGreater(self.win.compact_artist.get_max_width_chars(), 0)
        self.assertLessEqual(self.win.compact_artist.get_max_width_chars(), 26)

        self.win.show_all()
        self.win.compact_title.set_text("Title")
        self.win.compact_artist.set_text("An Extremely Long Artist Name That Takes Substantial Horizontal Space")
        alloc = notch.Gdk.Rectangle()
        alloc.width = 440
        alloc.height = 250
        self.win._overlay.size_allocate(alloc)

        col_w = self.win.compact_title.get_parent().get_allocation().width
        art_w = self.win.compact_artist.get_allocation().width
        self.assertEqual(art_w, col_w)
        self.assertEqual(col_w, 196)

    def test_compact_dimensions_remain_280x44_with_long_metadata(self):
        """Verify compact dimensions remain strictly 280x44 across varied metadata strings."""
        self.win.show_all()
        alloc = notch.Gdk.Rectangle()
        alloc.width = 440
        alloc.height = 250

        test_cases = [
            ("Normal Title", "Normal Artist"),
            ("Backburner", "NIKI"),
            ("Backburner (Extended Remastered Version)", "NIKI"),
            ("Bohemian Rhapsody (2011 Remastered Version)", "Queen & David Bowie"),
            ("WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW", "MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM"),
            ("A" * 350, "B" * 350),
            ("Title with\nline break", "Artist with\nline break"),
            ("🎧 🎵 日本語の曲名テスト 🚀", "アーティスト名"),
        ]

        for t, a in test_cases:
            info = {"title": t, "artist": a, "status": "Playing"}
            self.win._last_info = info
            self.win._update_compact_ui()
            self.win._overlay.size_allocate(alloc)

            box_alloc = self.win._compact_box.get_allocation()
            self.assertEqual(box_alloc.width, notch.COMPACT_W)
            self.assertEqual(box_alloc.height, notch.COMPACT_H)

            # Confirm title and artist remain single-line
            title_layout = self.win.compact_title.get_layout()
            artist_layout = self.win.compact_artist.get_layout()
            self.assertEqual(title_layout.get_line_count(), 1)
            self.assertEqual(artist_layout.get_line_count(), 1)

            # Confirm artwork and equalizer remain in bounds without displacement
            art_alloc = self.win.compact_art_container.get_allocation()
            title_alloc = self.win.compact_title.get_allocation()
            act_alloc = self.win.compact_activity.get_allocation()
            self.assertEqual(art_alloc.width, notch.ART_SIZE_COMPACT)
            self.assertEqual(art_alloc.height, notch.ART_SIZE_COMPACT)
            self.assertEqual(act_alloc.width, 14)
            self.assertEqual(act_alloc.height, 14)
            self.assertLessEqual(art_alloc.x + art_alloc.width, title_alloc.x)
            self.assertLessEqual(title_alloc.x + title_alloc.width, act_alloc.x)

    def test_existing_three_element_compact_layout_preserved(self):
        """Verify the compact container retains its original three-element structure."""
        children = self.win._compact_box.get_children()
        self.assertEqual(len(children), 3)
        self.assertEqual(children[0], self.win.compact_art_container)
        self.assertEqual(children[1], self.win.compact_title.get_parent())
        self.assertEqual(children[2], self.win.compact_activity)

        self.assertEqual(self.win.compact_art_container.get_size_request(), (notch.ART_SIZE_COMPACT, notch.ART_SIZE_COMPACT))
        self.assertEqual(self.win.compact_activity.get_size_request(), (14, 14))

    def test_expanded_title_presentation_unaffected(self):
        """Verify expanded title presentation remains unaffected by compact constraints."""
        self.assertEqual(self.win.full_title.get_max_width_chars(), 26)
        self.assertEqual(self.win.full_artist.get_max_width_chars(), 30)
        self.assertEqual(self.win._full_box.get_size_request(), (notch.EXPANDED_W, notch.EXPANDED_H))

        self.win._last_info = {
            "title": "An Extremely Long Track Title In Expanded View That Spans Far",
            "artist": "An Extremely Long Artist Name In Expanded View",
            "status": "Playing"
        }
        self.win._update_full_ui()
        self.assertEqual(self.win.full_title.get_text(), "An Extremely Long Track Title In Expanded View That Spans Far")
        self.assertEqual(self.win.full_artist.get_text(), "An Extremely Long Artist Name In Expanded View")

    def test_persistent_bluetooth_ui_remains_intact(self):
        """Verify persistent Bluetooth headset UI and state tracking remain intact."""
        info = {
            "name": "soundcore R60i NC",
            "percent": 85,
            "battery_text": "85%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": "/org/bluez/hci0/dev_99"
        }
        self.win._update_persistent_bt(info)
        self.assertIsNotNone(self.win._persistent_bt_device)
        self.assertEqual(self.win._persistent_bt_device["name"], "soundcore R60i NC")
        self.assertTrue(self.win.full_bt_box.get_visible())
        self.assertEqual(self.win.full_bt_name.get_text(), "🎧 soundcore R60i NC")
        self.assertEqual(self.win.full_bt_battery.get_text(), "Battery 85%")

        # Verify compact box does not have BT widgets
        self.assertFalse(hasattr(self.win, "compact_bt_label"))
        self.assertEqual(len(self.win._compact_box.get_children()), 3)


class TestExpandedMetadataLayout(unittest.TestCase):
    """Test suite validating expanded track metadata, header layout, and element boundaries."""

    def setUp(self):
        self.win = notch.DynamicIslandWindow()

    def tearDown(self):
        self.win._on_delete()
        self.win.destroy()

    def test_expanded_metadata_packing_and_no_overlap(self):
        """Verify extremely long track title and artist do not overlap header elements or push Bluetooth status."""
        self.win.show_all()
        alloc = notch.Gdk.Rectangle()
        alloc.width = 440
        alloc.height = 250

        # Connected headset to test Bluetooth header presence
        info_bt = {
            "name": "soundcore R60i NC",
            "percent": 85,
            "battery_text": "85%",
            "components": {},
            "is_laptop": False,
            "connected": True,
            "path": "/org/bluez/hci0/dev_99"
        }
        self.win._update_persistent_bt(info_bt)

        # Extremely long metadata (350+ characters)
        long_title = "An Extremely Long Track Title In Expanded View That Spans " * 8
        long_artist = "An Extremely Long Artist Name In Expanded View " * 8
        self.win._last_info = {
            "title": long_title,
            "artist": long_artist,
            "status": "Playing",
            "length_us": 240000000,
            "position_us": 60000000
        }
        self.win._update_full_ui()
        self.win._overlay.size_allocate(alloc)

        # 1. Header elements bounds and packing: art -> info -> bt -> act
        art_alloc = self.win.art_container.get_allocation()
        info_alloc = self.win.full_title.get_parent().get_allocation()
        bt_alloc = self.win.full_bt_box.get_allocation()
        act_alloc = self.win.full_activity.get_allocation()

        self.assertGreaterEqual(art_alloc.x, 20)
        self.assertLessEqual(art_alloc.x + art_alloc.width, info_alloc.x)
        self.assertLessEqual(info_alloc.x + info_alloc.width, bt_alloc.x)
        self.assertLessEqual(bt_alloc.x + bt_alloc.width, act_alloc.x)
        self.assertLessEqual(act_alloc.x + act_alloc.width, 420)

        # 2. Bluetooth status remains visible and intact
        self.assertTrue(self.win.full_bt_box.get_visible())
        self.assertEqual(self.win.full_bt_name.get_text(), "🎧 soundcore R60i NC")
        self.assertEqual(self.win.full_bt_battery.get_text(), "Battery 85%")

        # 3. Title and artist remain single-line with end-ellipsization
        self.assertTrue(self.win.full_title.get_single_line_mode())
        self.assertFalse(self.win.full_title.get_line_wrap())
        self.assertEqual(self.win.full_title.get_ellipsize(), notch.Pango.EllipsizeMode.END)
        self.assertEqual(self.win.full_title.get_layout().get_line_count(), 1)

        self.assertTrue(self.win.full_artist.get_single_line_mode())
        self.assertFalse(self.win.full_artist.get_line_wrap())
        self.assertEqual(self.win.full_artist.get_ellipsize(), notch.Pango.EllipsizeMode.END)
        self.assertEqual(self.win.full_artist.get_layout().get_line_count(), 1)

        # 4. Artwork, seekbar, controls unaffected
        self.assertEqual(self.win.art_container.get_size_request(), (notch.ART_SIZE_EXPANDED, notch.ART_SIZE_EXPANDED))
        self.assertTrue(self.win.seek_scale.get_allocated_height() > 0)

        # 5. Full box dimensions strictly 400 x 178
        fb_alloc = self.win._full_box.get_allocation()
        self.assertEqual(fb_alloc.width, notch.EXPANDED_W)
        self.assertEqual(fb_alloc.height, notch.EXPANDED_H)


if __name__ == "__main__":
    unittest.main()
