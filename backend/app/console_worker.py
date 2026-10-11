"""Independent bounded workspace loops; persistent jobs survive process death."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import time

import httpx
import psycopg2

from .config import Settings
from .database import Database
from .evidence import collect
from .jobs import ReadFailure, claim, fail
from .reconciliation import schedule_page
from .repairs import run_repair


def run_one(app,workspace,*,foreground_first=True):
    job=claim(app.state.database,workspace,foreground_first=foreground_first)
    if job is None:
        return False
    try:
        collect(app,job)
    except ReadFailure as error:
        fail(app.state.database,job,error)
    except psycopg2.Error:
        fail(app.state.database,job,ReadFailure("database_unavailable"))
    return True


def run_workspace(settings,database,workspace,stop,marker):
    # A source-budget wait in one business must not occupy the other loop.
    # Each loop owns its HTTP client; transactions use the threaded DB pool.
    marker=Path(str(marker)+'-'+workspace)
    marker.unlink(missing_ok=True)
    with httpx.Client(timeout=5,trust_env=False) as client:
        app=SimpleNamespace(state=SimpleNamespace(settings=settings,database=database,http=client))
        next_scan=0
        rounds=0
        while not stop.is_set():
            marker.touch()
            if time.monotonic()>=next_scan:
                connections=[f'sim_{workspace}']+([f'stripe_{workspace}'] if workspace in settings.stripe else [])
                for connection_id in connections:
                    schedule_page(database,workspace,connection_id)
                next_scan=time.monotonic()+1
            # Four foreground-preferred turns, then a background-preferred turn.
            # Empty queues fall back to available work; budgets still govern reads.
            run_one(app,workspace,foreground_first=rounds%5!=4)
            rounds+=1
            run_repair(app,workspace)
            marker.touch()
            stop.wait(.25)


def main():
    marker=Path("/tmp/console-worker-heartbeat")
    marker.unlink(missing_ok=True)
    settings=Settings.from_env("console")
    database=Database(settings.database_url)
    stop=Event()
    try:
        if settings.stripe:
            from .stripe_provider import configure_connections
            configure_connections(database,settings)
        # Configuration contains two local workspaces: fixed bounded concurrency.
        with ThreadPoolExecutor(max_workers=len(settings.keys)) as pool:
            futures=[pool.submit(run_workspace,settings,database,workspace,stop,marker)
                     for workspace in settings.keys]
            try:
                finished,_=wait(futures,return_when=FIRST_COMPLETED)
                # Fail the process if any workspace loop fails; do not silently
                # leave one workspace unserviced while the other looks healthy.
                for future in finished:
                    future.result()
            finally:
                stop.set()
    finally:
        database.close()


if __name__=="__main__":
    main()
