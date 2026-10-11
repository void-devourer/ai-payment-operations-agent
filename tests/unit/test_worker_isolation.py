"""A waiting workspace must not prevent another workspace from running."""
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from backend.app import console_worker


class StopWorker(Exception):
    pass


class WorkerIsolationTests(unittest.TestCase):
    def test_one_in_five_turns_prefers_background(self):
        stop=Event()
        preferences=[]
        def read(app, workspace, *, foreground_first):
            preferences.append(foreground_first)
            if len(preferences)==5:
                stop.set()
        settings=SimpleNamespace(stripe={},keys={'ws_a':{}},database_url='unused')
        with patch.object(console_worker.httpx,'Client'), \
             patch.object(console_worker,'run_one',side_effect=read), \
             patch.object(console_worker,'run_repair'), \
             patch.object(console_worker,'schedule_page'), \
             patch.object(Path,'touch'),patch.object(Path,'unlink'), \
             patch.object(stop,'wait',return_value=False):
            console_worker.run_workspace(settings,MagicMock(),'ws_a',stop,Path('/unused'))
        self.assertEqual(preferences,[True,True,True,True,False])

    def test_budget_wait_in_a_does_not_block_b(self):
        entered_a, release_a, entered_b = Event(), Event(), Event()
        failures = []
        settings = SimpleNamespace(keys={'ws_a': {}, 'ws_b': {}}, stripe={}, database_url='unused')
        database = MagicMock()

        def read(app, workspace, **kwargs):
            if workspace == 'ws_a':
                entered_a.set()
                if not release_a.wait(3):
                    raise AssertionError('Test wait exceeded bound')
            else:
                entered_b.set()
                raise StopWorker()

        def start():
            try:
                console_worker.main()
            except StopWorker:
                pass
            except Exception as error:
                failures.append(type(error).__name__)

        with patch.object(console_worker.Settings, 'from_env', return_value=settings), \
             patch.object(console_worker, 'Database', return_value=database), \
             patch.object(console_worker.httpx, 'Client'), \
             patch.object(console_worker, 'run_one', side_effect=read), \
             patch.object(console_worker, 'run_repair'), \
             patch.object(console_worker, 'schedule_page'), \
             patch.object(Path, 'touch'), patch.object(Path, 'unlink'):
            thread = Thread(target=start, daemon=True)
            thread.start()
            try:
                self.assertTrue(entered_a.wait(1), 'Workspace A never entered its read')
                self.assertTrue(entered_b.wait(.5), 'Workspace B was blocked by A')
            finally:
                release_a.set()
                thread.join(3)
            self.assertFalse(thread.is_alive(), 'Worker did not shut down')
            self.assertEqual(failures, [])
            database.close.assert_called_once()
