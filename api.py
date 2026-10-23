"""HTTP API for store analytics and OpenAI tool access."""
from typing import Any
import sqlite3

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ai_agent import TOOLS, ask_openai
from db import database_schema, query_database, store_names

app = FastAPI(title="Store Intelligence API", version="2.0.0")


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=1500)
    context: dict[str, Any] = Field(default_factory=dict)


class Command(BaseModel):
    command: str = Field(min_length=2, max_length=1500)
    context: dict[str, Any] = Field(default_factory=dict)


class SqlQuery(BaseModel):
    sql: str = Field(min_length=1, max_length=20000)


@app.get("/api/health")
def health():
    return {"status": "ok", "stores": store_names()}


@app.get("/api/schema")
def schema():
    return database_schema()


@app.post("/api/query")
def query(request: SqlQuery):
    try:
        return query_database(request.sql)
    except (ValueError, sqlite3.Error) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/ask")
def ask(request: Question):
    try:
        return ask_openai(request.question, request.context or None)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/dashboard/command")
def dashboard_command(request: Command):
    try:
        return ask_openai(request.command, request.context or None)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/tools")
def tools_catalog():
    return {"tools": TOOLS, "note": "State updates returned by the API must be applied by its UI client; the Streamlit chat does so automatically."}
