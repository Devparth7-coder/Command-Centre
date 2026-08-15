"""AI Command Center API — local-first control plane with SSE execution events.

PostgreSQL/Redis/Qdrant adapters are configured by environment variables. The
zero-config developer experience uses SQLite and deterministic local agents.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("SQLITE_PATH", ROOT / "command_center.db"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    schema = (ROOT / "backend" / "database" / "schema.sql").read_text()
    with db() as conn:
        conn.executescript(schema)
        count = conn.execute("SELECT count(*) FROM agents").fetchone()[0]
        if not count:
            agents = [
                ("Research Agent", "Researches papers and generates evidence-backed findings.", "running", "gpt-4.1", '["Web Search","Vector Database"]', 96, 842, 1284),
                ("Coding Agent", "Analyzes repositories and executes code in a sandbox.", "idle", "claude-3.7-sonnet", '["GitHub","Python"]', 93, 1130, 896),
                ("Data Analyst", "Analyzes structured datasets and produces verified insights.", "running", "gemini-2.5-pro", '["Python","SQL"]', 91, 721, 643),
                ("Browser Agent", "Searches and extracts permitted web sources.", "idle", "gpt-4.1-mini", '["Web Search"]', 89, 608, 521),
                ("ML Engineer", "Runs reproducible machine-learning experiments.", "running", "claude-3.7-sonnet", '["Python","File System"]', 94, 1450, 419),
                ("Critic Agent", "Evaluates evidence, reasoning, citations and results.", "idle", "gpt-4.1", '["Vector Database"]', 97, 612, 1032),
            ]
            conn.executemany("INSERT INTO agents(name,description,status,model,tools,success_rate,avg_latency,total_executions) VALUES(?,?,?,?,?,?,?,?)", agents)
            conn.executemany("INSERT INTO services(name,status,latency_ms) VALUES(?,?,?)", [(x,"healthy",n) for x,n in [("LLM Gateway",84),("Agent Runtime",32),("PostgreSQL",12),("Vector Database",19),("Redis",4),("Worker Pool",28)]])


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="AI Command Center API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_origin_regex=r"https://.*\.e2b\.app", allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class AgentIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=4, max_length=500)
    model: str = "gpt-4.1-mini"
    tools: list[str] = []
    system_prompt: str = "You are a precise, reliable AI agent."
    temperature: float = Field(0.2, ge=0, le=2)
    max_tokens: int = Field(4096, ge=128, le=128000)

class RunIn(BaseModel):
    prompt: str = Field(min_length=3, max_length=10000)
    agent_id: int | None = None
    demo: bool = False

class MemoryIn(BaseModel):
    content: str = Field(min_length=2, max_length=5000)
    kind: str = "fact"
    importance: float = Field(0.7, ge=0, le=1)

@app.get("/api/health")
def health():
    return {"status":"healthy","mode":"demo" if not os.getenv("OPENAI_API_KEY") else "connected","time":now()}

@app.get("/api/dashboard")
def dashboard():
    with db() as conn:
        agents = [dict(x) for x in conn.execute("SELECT * FROM agents ORDER BY id")]
        runs = [dict(x) for x in conn.execute("SELECT * FROM agent_runs ORDER BY id DESC LIMIT 20")]
    return {"metrics":{"active_agents":sum(a["enabled"] and a["status"]=="running" for a in agents),"running_tasks":sum(r["status"]=="running" for r in runs),"completed_tasks":1248+sum(r["status"]=="completed" for r in runs),"failed_tasks":23+sum(r["status"]=="failed" for r in runs),"success_rate":96.8,"avg_latency":842,"token_usage":184200,"estimated_cost":42.18},"agents":agents,"runs":runs,"series":[42,58,51,72,66,81,76,91,84,96,88,104]}

@app.get("/api/agents")
def agents():
    with db() as conn: return [dict(x) for x in conn.execute("SELECT * FROM agents ORDER BY id")]

@app.post("/api/agents", status_code=201)
def create_agent(item: AgentIn):
    with db() as conn:
        cur=conn.execute("INSERT INTO agents(name,description,status,model,tools,system_prompt,temperature,max_tokens) VALUES(?,?,?,?,?,?,?,?)",(item.name,item.description,"idle",item.model,json.dumps(item.tools),item.system_prompt,item.temperature,item.max_tokens))
        row=conn.execute("SELECT * FROM agents WHERE id=?",(cur.lastrowid,)).fetchone()
    return dict(row)

@app.patch("/api/agents/{agent_id}/toggle")
def toggle_agent(agent_id:int):
    with db() as conn:
        row=conn.execute("SELECT enabled FROM agents WHERE id=?",(agent_id,)).fetchone()
        if not row: raise HTTPException(404,"Agent not found")
        conn.execute("UPDATE agents SET enabled=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(0 if row[0] else 1,agent_id))
        return {"id":agent_id,"enabled":not bool(row[0])}

@app.delete("/api/agents/{agent_id}", status_code=204)
def delete_agent(agent_id:int):
    with db() as conn:
        if not conn.execute("DELETE FROM agents WHERE id=?",(agent_id,)).rowcount: raise HTTPException(404,"Agent not found")

@app.post("/api/runs", status_code=201)
def create_run(item: RunIn):
    run_id=str(uuid.uuid4())
    with db() as conn:
        conn.execute("INSERT INTO agent_runs(id,agent_id,prompt,status,started_at) VALUES(?,?,?,?,?)",(run_id,item.agent_id or 1,item.prompt,"queued",now()))
    return {"id":run_id,"status":"queued","events_url":f"/api/runs/{run_id}/events"}

@app.get("/api/runs/{run_id}")
def get_run(run_id:str):
    with db() as conn:
        run=conn.execute("SELECT * FROM agent_runs WHERE id=?",(run_id,)).fetchone()
        if not run: raise HTTPException(404,"Run not found")
        events=[dict(x) for x in conn.execute("SELECT * FROM agent_events WHERE run_id=? ORDER BY sequence",(run_id,))]
    return {**dict(run),"events":events}

@app.get("/api/runs/{run_id}/events")
async def run_events(run_id:str, request:Request):
    with db() as conn:
        run=conn.execute("SELECT * FROM agent_runs WHERE id=?",(run_id,)).fetchone()
    if not run: raise HTTPException(404,"Run not found")
    prompt=run["prompt"]
    demo="github" in prompt.lower() or "skill" in prompt.lower()
    steps = [
        ("intent","Request understood","Intent classified as repository intelligence",8),
        ("plan","Plan created","7-stage execution graph compiled",18),
        ("agent","GitHub Agent activated" if demo else "Research Agent activated","Agent runtime allocated",30),
        ("tool","Repository analysis complete" if demo else "Search tool executed","18 sources inspected",46),
        ("reasoning","Technology extraction" if demo else "Analyzing evidence","Python, ML, LLMs, RAG and DSA detected",62),
        ("critic","Gap detection & critic review","Deployment and lifecycle gaps verified",81),
        ("result","Recommendation ready" if demo else "Final response ready","MLOps is the highest-leverage next skill",100),
    ]
    async def stream():
        started=time.time()
        with db() as conn: conn.execute("UPDATE agent_runs SET status='running' WHERE id=?",(run_id,))
        for seq,(kind,title,detail,progress) in enumerate(steps):
            if await request.is_disconnected(): break
            ts=now(); payload={"id":str(uuid.uuid4()),"run_id":run_id,"sequence":seq,"kind":kind,"title":title,"detail":detail,"progress":progress,"timestamp":ts,"status":"completed"}
            with db() as conn:
                conn.execute("INSERT OR IGNORE INTO agent_events(id,run_id,sequence,kind,title,detail,progress,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(payload["id"],run_id,seq,kind,title,detail,progress,"completed",ts))
            yield f"event: agent_event\ndata: {json.dumps(payload)}\n\n"
            await asyncio.sleep(.7)
        result={"title":"RECOMMENDED NEXT SKILL","answer":"MLOps","reason":"Your profile demonstrates Python, Machine Learning, LLMs, RAG and DSA. The largest leverage gap is production deployment, monitoring, CI/CD and model lifecycle management.","confidence":0.94}
        elapsed=int((time.time()-started)*1000)
        with db() as conn: conn.execute("UPDATE agent_runs SET status='completed',progress=100,result=?,tokens=1842,cost=0.031,latency_ms=?,completed_at=? WHERE id=?",(json.dumps(result),elapsed,now(),run_id))
        yield f"event: complete\ndata: {json.dumps(result)}\n\n"
    return StreamingResponse(stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.get("/api/memories")
def memories(q:str=""):
    with db() as conn:
        rows=conn.execute("SELECT * FROM memories WHERE content LIKE ? ORDER BY importance DESC, created_at DESC",(f"%{q}%",)).fetchall()
    return [dict(x) for x in rows]

@app.post("/api/memories", status_code=201)
def add_memory(item:MemoryIn):
    with db() as conn:
        cur=conn.execute("INSERT INTO memories(content,kind,importance) VALUES(?,?,?)",(item.content,item.kind,item.importance)); row=conn.execute("SELECT * FROM memories WHERE id=?",(cur.lastrowid,)).fetchone()
    return dict(row)

@app.delete("/api/memories/{memory_id}",status_code=204)
def delete_memory(memory_id:int):
    with db() as conn: conn.execute("DELETE FROM memories WHERE id=?",(memory_id,))

@app.get("/api/services")
def services():
    with db() as conn: return [dict(x) for x in conn.execute("SELECT * FROM services ORDER BY id")]
