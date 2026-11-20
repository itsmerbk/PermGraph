# PermGraph

**Google Zanzibar-Style Relationship-Based Access Control (ReBAC) Graph Engine**

PermGraph replaces brittle role-checking conditionals with a centralized, graph-backed authorization engine. It resolves multi-hop organizational hierarchies, userset rewrites, and role implications (`owner -> editor -> viewer`) with cycle-safe DFS traversal, explainable proof paths, and revision-stamped cache invalidation.

## Architecture

~~~mermaid
flowchart LR
    A[Service / API Gateway] -->|POST /v1/check| B[PermGraph Resolver]
    B --> C{Revision Cache Hit?}
    C -->|Yes: ~0.002 ms| D[ALLOW / DENY + Proof Path]
    C -->|No: Cold Check| E[Cycle-Guarded DFS Engine]
    E -->|Usersets + Parent Edges| F[(SQLite WAL Tuple Store)]
    G[POST/DELETE /v1/tuples] -->|Increment Zookie Revision| F
    F -->|Invalidate Stale Cache| C
~~~

## Quickstart

~~~bash
git clone https://github.com/itsmerbk/perm-graph.git
cd perm-graph
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Run unit tests (inheritance, cycle guard, instant revocation)
pytest -v

# 2. Run explainability audit & 5,000-check latency benchmark
python -m permgraph.demo_benchmark

# 3. Start the REST Authorization API (http://127.0.0.1:8096/docs)
uvicorn permgraph.app:app --reload --port 8096
~~~
