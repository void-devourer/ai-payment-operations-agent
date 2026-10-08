"""One bounded job per workspace per round; persistent jobs survive process death."""

from pathlib import Path
from types import SimpleNamespace
import time

import httpx
import psycopg2

from .config import Settings
from .database import Database
from .evidence import collect
from .jobs import ReadFailure, claim, fail


def run_one(app,workspace):
    job=claim(app.state.database,workspace)
    if job is None:
        return False
    try:
        collect(app,job)
    except ReadFailure as error:
        fail(app.state.database,job,error)
    except psycopg2.Error:
        fail(app.state.database,job,ReadFailure("database_unavailable"))
    return True


def main():
    marker=Path("/tmp/console-worker-heartbeat")
    marker.unlink(missing_ok=True)
    settings=Settings.from_env("console")
    database=Database(settings.database_url)
    try:
        with httpx.Client(timeout=5,trust_env=False) as client:
            app=SimpleNamespace(state=SimpleNamespace(settings=settings,database=database,http=client))
            while True:
                for workspace in settings.keys:
                    marker.touch()
                    run_one(app,workspace)
                marker.touch()
                time.sleep(.25)
    finally:
        database.close()


if __name__=="__main__":
    main()
