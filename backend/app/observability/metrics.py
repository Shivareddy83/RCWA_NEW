from __future__ import annotations
import threading
from collections import defaultdict
from typing import Iterable

_LOCK = threading.RLock()
_COUNTERS: dict[str, dict[tuple[tuple[str, str], ...], float]] = defaultdict(dict)
_HIST: dict[str, dict[tuple[tuple[str, str], ...], dict[str, float]]] = defaultdict(dict)
_GAUGES: dict[str, dict[tuple[tuple[str, str], ...], float]] = defaultdict(dict)
_KNOWN_COUNTERS = {
    "http_requests_total", "ingestion_batches_total", "ingestion_records_received_total",
    "ingestion_records_created_total", "ingestion_records_updated_total", "ingestion_records_duplicate_total",
    "ingestion_records_rejected_total", "reconciliation_runs_total", "reconciliation_matches_total",
    "reconciliation_unmatched_total", "reconciliation_ambiguous_total", "reconciliation_mismatches_total",
    "exceptions_created_total", "exceptions_resolved_total", "exceptions_reopened_total", "exceptions_acknowledged_total",
    "cases_created_total", "cases_resolved_total", "cases_reopened_total", "case_assignments_total", "case_notes_added_total",
    "ai_investigations_total", "ai_investigations_success_total", "ai_investigations_failed_total", "ai_investigations_reused_total",
    "audit_events_created_total", "audit_events_failed_total", "audit_events_denied_total",
    "jobs_created_total", "jobs_started_total", "jobs_succeeded_total", "jobs_failed_total", "jobs_retried_total", "jobs_dead_lettered_total", "jobs_stale_recovered_total",
}

HTTP_LABELS = ("method", "route", "status")
INGESTION_LABELS = ("source_type",)
RECON_LABELS = ("match_method", "result")
EXCEPTION_LABELS = ("exception_code", "severity")
CASE_LABELS = ("status", "priority", "resolution_code")
AI_LABELS = ("failure_category", "provider")
JOB_LABELS = ("job_type", "status", "failure_category")
_ALLOWED_LABELS = {
    **{name: HTTP_LABELS for name in {"http_requests_total"}},
    **{name: INGESTION_LABELS for name in {"ingestion_batches_total", "ingestion_records_received_total", "ingestion_records_created_total", "ingestion_records_updated_total", "ingestion_records_duplicate_total", "ingestion_records_rejected_total"}},
    **{name: RECON_LABELS for name in {"reconciliation_matches_total", "reconciliation_unmatched_total", "reconciliation_ambiguous_total", "reconciliation_mismatches_total"}},
    **{name: EXCEPTION_LABELS for name in {"exceptions_created_total", "exceptions_resolved_total", "exceptions_reopened_total", "exceptions_acknowledged_total"}},
    **{name: CASE_LABELS for name in {"cases_created_total", "cases_resolved_total", "cases_reopened_total", "case_assignments_total", "case_notes_added_total"}},
    **{name: AI_LABELS for name in {"ai_investigations_total", "ai_investigations_success_total", "ai_investigations_failed_total"}},
    **{name: JOB_LABELS for name in {"jobs_created_total", "jobs_started_total", "jobs_succeeded_total", "jobs_failed_total", "jobs_retried_total", "jobs_dead_lettered_total"}},
}

HISTOGRAM_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

def _labels(names: Iterable[str], values: Iterable[object]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((n, str(v)) for n, v in zip(names, values)))

def inc(name: str, value: float = 1, *, labels: dict[str, object] | None = None) -> None:
    supplied = labels or {}
    allowed = _ALLOWED_LABELS.get(name)
    if allowed is not None:
        supplied = {k: v for k, v in supplied.items() if k in allowed}
    key = _labels(supplied.keys(), supplied.values())
    with _LOCK:
        _COUNTERS[name][key] = _COUNTERS[name].get(key, 0) + value

def set_gauge(name: str, value: float, *, labels: dict[str, object] | None = None) -> None:
    supplied = labels or {}
    allowed = _ALLOWED_LABELS.get(name)
    if allowed is not None: supplied = {k: v for k, v in supplied.items() if k in allowed}
    key = _labels(supplied.keys(), supplied.values())
    with _LOCK:
        _GAUGES[name][key] = value

def observe(name: str, value: float, *, labels: dict[str, object] | None = None) -> None:
    supplied = labels or {}
    allowed = _ALLOWED_LABELS.get(name)
    if allowed is not None: supplied = {k: v for k, v in supplied.items() if k in allowed}
    key = _labels(supplied.keys(), supplied.values())
    with _LOCK:
        item = _HIST[name].setdefault(key, {"count": 0, "sum": 0.0, **{f"bucket:{b}": 0 for b in HISTOGRAM_BUCKETS}})
        item["count"] += 1
        item["sum"] += value
        for bucket in HISTOGRAM_BUCKETS:
            if value <= bucket:
                item[f"bucket:{bucket}"] += 1

def _fmt_labels(labels: tuple[tuple[str, str], ...], extra: tuple[str, str] | None = None) -> str:
    pairs = list(labels)
    if extra: pairs.append(extra)
    if not pairs: return ""
    return "{" + ",".join(f'{k}="{v.replace(chr(92), chr(92)+chr(92)).replace(chr(34), chr(92)+chr(34))}"' for k, v in pairs) + "}"

def render_prometheus() -> str:
    lines: list[str] = []
    with _LOCK:
        for name in sorted(_KNOWN_COUNTERS | set(_COUNTERS)):
            series = _COUNTERS.get(name, {})
            lines.append(f"# TYPE {name} counter")
            for labels, value in series.items(): lines.append(f"{name}{_fmt_labels(labels)} {value:g}")
        for name, series in sorted(_GAUGES.items()):
            lines.append(f"# TYPE {name} gauge")
            for labels, value in series.items(): lines.append(f"{name}{_fmt_labels(labels)} {value:g}")
        for name, series in sorted(_HIST.items()):
            lines.append(f"# TYPE {name} histogram")
            for labels, item in series.items():
                for bucket in HISTOGRAM_BUCKETS:
                    lines.append(f"{name}_bucket{_fmt_labels(labels, ('le', str(bucket)))} {item[f'bucket:{bucket}']:g}")
                lines.append(f"{name}_bucket{_fmt_labels(labels, ('le', '+Inf'))} {item['count']:g}")
                lines.append(f"{name}_sum{_fmt_labels(labels)} {item['sum']:g}")
                lines.append(f"{name}_count{_fmt_labels(labels)} {item['count']:g}")
    return "\n".join(lines) + ("\n" if lines else "")

def reset_metrics() -> None:
    with _LOCK:
        _COUNTERS.clear(); _HIST.clear(); _GAUGES.clear()
