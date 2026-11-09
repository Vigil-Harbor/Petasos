"""Benchmark-only resource observations; never changes child ownership or limits."""

from __future__ import annotations

import os
import threading
import time
from typing import TYPE_CHECKING, Any
from unittest.mock import patch
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from contextlib import ExitStack
    from pathlib import Path


class Resources:
    def __init__(self, runtime: Any) -> None:
        import psutil

        self.psutil = psutil
        self.parent = psutil.Process()
        self.runtime = runtime
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.roots: set[Path] = set()
        self.processes: dict[tuple[int, float], Any] = {}
        self.streams: WeakKeyDictionary[Any, list[int]] = WeakKeyDictionary()
        self.data: dict[str, Any] = {
            "interval_seconds": 0.1,
            "samples": 0,
            "missing": [],
            "parent_rss_peak_bytes": 0,
            "owned_rss_sampled_peak_bytes": 0,
            "retained_map_sampled_peak_bytes": 0,
            "map_charge_peak_per_selection_bytes": 0,
            "stdout_high_water_per_child_bytes": 0,
            "stderr_observed_per_child_bytes": 0,
            "source_characters_sampled_peak": 0,
            "control_loop_lag_max_seconds": 0.0,
            "control_loop_samples": 0,
        }
        self.thread = threading.Thread(
            target=self._run, name="semgrep-benchmark-monitor", daemon=True
        )
        self.probe_pending = threading.Event()

    def missing(self, field: str) -> None:
        with self.lock:
            if field not in self.data["missing"]:
                self.data["missing"].append(field)

    def peak(self, field: str, value: int | float) -> None:
        with self.lock:
            self.data[field] = max(self.data[field], value)

    def parent_counts(self) -> dict[str, int] | None:
        try:
            return {
                "handles_or_fds": self.parent.num_handles()
                if os.name == "nt"
                else self.parent.num_fds(),
                "threads": self.parent.num_threads(),
            }
        except self.psutil.Error:
            self.missing("parent_counts")
            return None

    def install(self, stack: ExitStack) -> None:
        from petasos.scanners import _semgrep_process as process
        from petasos.scanners import _semgrep_runtime as runtime
        from petasos.scanners._semgrep_source import MapBudget

        new_root = runtime.Runtime._new_root
        charge = MapBudget.charge
        child_type = process._WindowsChild if os.name == "nt" else process._PosixChild
        read = child_type.read

        def tracked_root(owner: Any, job: Any) -> Path:
            root = new_root(owner, job)
            with self.lock:
                self.roots.add(root)
            return root

        def tracked_charge(budget: Any, length: int) -> None:
            try:
                charge(budget, length)
            finally:
                self.peak("map_charge_peak_per_selection_bytes", budget.used)

        def tracked_read(child: Any, index: int) -> bytes:
            chunk = read(child, index)
            with self.lock:
                counts = self.streams.setdefault(child, [0, 0])
                counts[index] += len(chunk)
                field = (
                    "stdout_high_water_per_child_bytes"
                    if index == 0
                    else "stderr_observed_per_child_bytes"
                )
                self.data[field] = max(self.data[field], counts[index])
            return chunk

        stack.enter_context(patch.object(runtime.Runtime, "_new_root", tracked_root))
        stack.enter_context(patch.object(MapBudget, "charge", tracked_charge))
        stack.enter_context(patch.object(child_type, "read", tracked_read))
        self.data["before"] = self.parent_counts()
        self.thread.start()

    def _sample(self) -> None:
        self.peak("parent_rss_peak_bytes", self.parent.memory_info().rss)
        with self.runtime.lock:
            jobs = [*self.runtime.active, *(j for q in self.runtime.pending.values() for j in q)]
            pids = [j.child.pid for j in jobs if j.child is not None]
            sources = [j.source for j in jobs]
            source_chars = sum(len(source[0]) for source in sources if source is not None)
            maps = 0
            for job in jobs:
                selection = job.selection
                if selection is not None:
                    for target in selection.targets:
                        source_chars += len(target.region.text)
                        for array in (target.region.starts, target.region.ends):
                            if array is not None:
                                maps += len(array) * array.itemsize
        self.peak("source_characters_sampled_peak", source_chars)
        self.peak("retained_map_sampled_peak_bytes", maps)
        # Retain observations only for processes descended from an owned leader;
        # never signal or open native ownership handles here.
        for pid in pids:
            try:
                proc = self.psutil.Process(pid)
                for owned in (proc, *proc.children(recursive=True)):
                    self.processes[(owned.pid, owned.create_time())] = owned
            except self.psutil.NoSuchProcess:
                pass
            except self.psutil.Error:
                self.missing("owned_descendants")
        rss = 0
        for identity, proc in list(self.processes.items()):
            try:
                if proc.is_running() and proc.create_time() == identity[1]:
                    rss += proc.memory_info().rss
                else:
                    del self.processes[identity]
            except self.psutil.NoSuchProcess:
                del self.processes[identity]
            except self.psutil.Error:
                self.missing("owned_rss")
        self.peak("owned_rss_sampled_peak_bytes", rss)
        self.data["samples"] += 1
        if not self.probe_pending.is_set() and self.runtime.thread.is_alive():
            self.probe_pending.set()
            start = time.monotonic()

            def observed() -> None:
                self.peak("control_loop_lag_max_seconds", time.monotonic() - start)
                with self.lock:
                    self.data["control_loop_samples"] += 1
                self.probe_pending.clear()

            try:
                self.runtime.loop.call_soon_threadsafe(observed)
            except RuntimeError:
                self.probe_pending.clear()
                if not self.runtime.loop.is_closed():
                    raise
                # Normal shutdown can close the loop before its thread exits.
                # This produces no new lag sample, not a missing observation.
                # finish() still requires actual samples from the measured work.

    def _run(self) -> None:
        while not self.stop.is_set():
            try:
                self._sample()
            except Exception as exc:
                self.missing("monitor_" + type(exc).__name__)
            self.stop.wait(0.1)

    def finish(self) -> dict[str, Any]:
        self.stop.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            self.missing("monitor_stop")
        self.data["after"] = self.parent_counts()
        with self.lock:
            roots = tuple(self.roots)
        self.data["root_residue"] = sum(p.exists() for p in roots)
        live = 0
        if not self.thread.is_alive():
            for identity, proc in self.processes.items():
                try:
                    live += int(
                        proc.is_running()
                        and proc.create_time() == identity[1]
                        and proc.status() != self.psutil.STATUS_ZOMBIE
                    )
                except self.psutil.NoSuchProcess:
                    pass
                except self.psutil.Error:
                    self.missing("owned_residue")
        self.data["live_owned_processes"] = live
        self.data["runtime_residuals"] = self.runtime.residuals()
        if any(self.data["runtime_residuals"].values()):
            self.missing("runtime_residue")
        if not self.data["control_loop_samples"]:
            self.missing("control_loop_lag")
        return self.data
