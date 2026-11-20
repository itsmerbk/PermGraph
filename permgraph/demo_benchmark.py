import tempfile
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from permgraph.engine import PermGraphEngine

console = Console()


def percentile(sorted_vals: list[float], pct: float) -> float:
    idx = min(len(sorted_vals) - 1, int(round((pct / 100.0) * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def main() -> None:
    tmp_db = Path(tempfile.gettempdir()) / "permgraph_benchmark.db"
    tmp_db.unlink(missing_ok=True)
    eng = PermGraphEngine(db_path=tmp_db)

    # Build multi-hop enterprise authorization graph:
    # user:bharath -> owner of org:srm-cloud -> member of team:core-infra -> editor of folder:prod-k8s -> parent of doc:api-keys
    eng.write_tuple("org", "srm-cloud", "owner", "user", "bharath")
    eng.write_tuple("team", "core-infra", "member", "org", "srm-cloud", "member")
    eng.write_tuple("folder", "prod-k8s", "editor", "team", "core-infra", "member")
    eng.write_tuple("doc", "api-keys", "parent", "folder", "prod-k8s")
    eng.write_tuple("doc", "public-rfc", "viewer", "user", "guest-intern")

    # Intentional parent cycle to demonstrate cycle-safe DFS termination
    eng.write_tuple("folder", "cycle-a", "parent", "folder", "cycle-b")
    eng.write_tuple("folder", "cycle-b", "parent", "folder", "cycle-a")

    scenarios = [
        ("4-Hop Transitive Inheritance", ("doc", "api-keys", "viewer", "user", "bharath")),
        ("Unauthorized Cross-Tenant Check", ("doc", "api-keys", "editor", "user", "guest-intern")),
        ("Cyclic Folder Graph Safety", ("folder", "cycle-a", "viewer", "user", "bharath")),
    ]

    table = Table(title="PermGraph Zanzibar ReBAC Resolution & Explainability Audit", expand=True, border_style="cyan")
    table.add_column("Scenario", style="bold magenta", width=28)
    table.add_column("Decision", width=11)
    table.add_column("Graph Traversal Proof Path", width=55)

    for label, query in scenarios:
        res = eng.check(*query)
        badge = "[bold green]ALLOW[/bold green]" if res.allowed else "[bold red]DENY[/bold red]"
        proof = "  ==>  ".join(res.path) if res.path else "No valid authorization path (cycle-guarded)"
        table.add_row(label, badge, proof)

    console.print(table)

    # Benchmark 5,000 permission checks (cache miss vs revision-stamped cache hit)
    cold_latencies: list[float] = []
    for _ in range(500):
        eng._cache.clear()
        t0 = time.perf_counter()
        eng.check("doc", "api-keys", "viewer", "user", "bharath")
        cold_latencies.append((time.perf_counter() - t0) * 1000.0)

    warm_latencies: list[float] = []
    t_warm_start = time.perf_counter()
    for _ in range(4500):
        t0 = time.perf_counter()
        eng.check("doc", "api-keys", "viewer", "user", "bharath")
        warm_latencies.append((time.perf_counter() - t0) * 1000.0)
    warm_wall = time.perf_counter() - t_warm_start

    cold_latencies.sort()
    warm_latencies.sort()

    console.print(
        Panel.fit(
            f"[bold cyan]PermGraph Latency Benchmark (5,000 Authorization Checks)[/bold cyan]\n"
            f"• Cold SQLite Graph Traversal (500 checks) : p50 = [yellow]{percentile(cold_latencies, 50):.3f} ms[/yellow] | p99 = [yellow]{percentile(cold_latencies, 99):.3f} ms[/yellow]\n"
            f"• Zookie Snapshot Cache Hit (4,500 checks)  : p50 = [green]{percentile(warm_latencies, 50):.4f} ms[/green] | p99 = [green]{percentile(warm_latencies, 99):.4f} ms[/green] ({int(4500 / warm_wall):,} checks/sec)",
            border_style="bright_blue",
        )
    )


if __name__ == "__main__":
    main()
