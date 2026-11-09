"""Fresh-process test of permanently sealing process-wide admissions."""

import asyncio
import time
from unittest.mock import patch

from petasos.scanners import _semgrep_runtime as rt
from petasos.scanners._semgrep_engine import result_for
from petasos.scanners.semgrep import SemgrepLifecycleOwner, SemgrepScanner


async def fake_job(runtime: rt.Runtime, job: rt.Job) -> None:
    if job.selection is None:
        result = rt.error_result("unused")
        result = type(result)("semgrep", (), 0)
    else:
        while not job.cancelled.is_set():
            await asyncio.sleep(0.002)
        await asyncio.sleep(0.15)  # deterministic owned cleanup, no abandoned task
        result = result_for(job.selection, error="semgrep.cancelled")
    with runtime.lock:
        runtime.active.discard(job)
        if job.selection is None:
            runtime.probe = None
            runtime.availability_error = None
        job.future.set_result(result)
        runtime._pump()


async def main() -> None:
    with (
        patch("petasos.scanners.semgrep.supported_platform", return_value=True),
        patch("petasos.scanners.semgrep.monitor_available", return_value=True),
        patch.object(rt.Runtime, "_execute", fake_job),
    ):
        async with SemgrepLifecycleOwner() as owner:
            import os

            scanner = SemgrepScanner(
                owner=owner, engine_path=os.path.abspath("fake"), engine_sha256="a" * 64
            )
            while not scanner.availability()[0]:
                await asyncio.sleep(0.005)
            task = asyncio.create_task(scanner.prepare("eval(data)", binding=scanner))
            await asyncio.sleep(0.02)
            first = await asyncio.to_thread(
                rt.close_semgrep_runtime, deadline=time.monotonic() + 0.01
            )
            assert first.status == "timed_out", first
            assert first.jobs > 0
            second = await asyncio.to_thread(
                rt.close_semgrep_runtime, deadline=time.monotonic() + 2
            )
            assert second.status == "closed", second
            token = await task
            assert token.outcome.error == "semgrep.cancelled"
            assert (await token.discard()).error == "semgrep.cancelled"
            assert token._text is None
            third = rt.close_semgrep_runtime(deadline=time.monotonic() + 1)
            assert second == third
            assert rt.acquire(scanner.settings, object()) == "semgrep.runtime_closed"
            assert (await scanner.scan("hello")).error == "semgrep.lease_closed"


if __name__ == "__main__":
    asyncio.run(main())
