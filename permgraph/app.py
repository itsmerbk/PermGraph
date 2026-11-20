from fastapi import FastAPI
from pydantic import BaseModel, Field

from permgraph.engine import PermGraphEngine

app = FastAPI(
    title="PermGraph",
    description="Google Zanzibar-Style Relationship-Based Access Control (ReBAC) Graph Engine",
    version="1.0.0",
)

engine = PermGraphEngine()


class TuplePayload(BaseModel):
    object_ns: str = Field(..., examples=["doc"])
    object_id: str = Field(..., examples=["prod-runbook"])
    relation: str = Field(..., examples=["parent"])
    subject_ns: str = Field(..., examples=["folder"])
    subject_id: str = Field(..., examples=["infra"])
    subject_relation: str = Field(default="")


class CheckPayload(BaseModel):
    object_ns: str
    object_id: str
    permission: str
    subject_ns: str = "user"
    subject_id: str


@app.post("/v1/tuples", status_code=201)
async def add_tuple(body: TuplePayload):
    rev = engine.write_tuple(
        body.object_ns,
        body.object_id,
        body.relation,
        body.subject_ns,
        body.subject_id,
        body.subject_relation,
    )
    return {"status": "written", "revision": rev}


@app.delete("/v1/tuples")
async def remove_tuple(body: TuplePayload):
    rev = engine.delete_tuple(
        body.object_ns,
        body.object_id,
        body.relation,
        body.subject_ns,
        body.subject_id,
        body.subject_relation,
    )
    return {"status": "deleted", "revision": rev}


@app.post("/v1/check")
async def check_permission(body: CheckPayload):
    outcome = engine.check(
        body.object_ns,
        body.object_id,
        body.permission,
        body.subject_ns,
        body.subject_id,
    )
    return {
        "allowed": outcome.allowed,
        "revision": outcome.revision,
        "cache_hit": outcome.cache_hit,
    }


@app.post("/v1/explain")
async def explain_permission(body: CheckPayload):
    outcome = engine.check(
        body.object_ns,
        body.object_id,
        body.permission,
        body.subject_ns,
        body.subject_id,
    )
    return {
        "allowed": outcome.allowed,
        "revision": outcome.revision,
        "resolution_path": outcome.path,
    }


@app.get("/v1/stats")
async def get_stats():
    return engine.stats()
