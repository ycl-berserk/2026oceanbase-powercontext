from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .memory import MemoryUnavailable
from .service import ReviewMateService, build_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.service = build_service()
    try:
        yield
    finally:
        app.state.service.close()


app = FastAPI(
    title="温故 ReviewMate",
    description="seekdb 混合检索 + PowerContext 学习记忆的课程笔记复习助手",
    version="0.1.0",
    lifespan=lifespan,
)


def get_service(request: Request) -> ReviewMateService:
    service = getattr(request.app.state, "service", None)
    if service is None:
        service = build_service()
        request.app.state.service = service
    return service


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str = "demo"
    course: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)


class WeakPointRequest(BaseModel):
    session_id: str = "demo"
    topic: str = Field(min_length=1, max_length=300)
    detail: str = Field(default="", max_length=600)


class NoteRequest(BaseModel):
    session_id: str = "demo"
    text: str = Field(min_length=1, max_length=2000)


class PlanRequest(BaseModel):
    session_id: str = "demo"
    course: str | None = None


@app.get("/api/health")
def health(request: Request) -> dict:
    return get_service(request).health()


@app.get("/api/documents")
def documents(request: Request) -> dict:
    service = get_service(request)
    return {"documents": service.documents(), "courses": service.courses()}


@app.post("/api/ask")
def ask(payload: AskRequest, request: Request) -> dict:
    service = get_service(request)
    try:
        result = service.ask(
            payload.question,
            session_id=payload.session_id,
            course=payload.course,
            top_k=payload.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.to_dict()


@app.get("/api/memory")
def memory_entries(
    request: Request,
    session_id: str = Query(default="demo", max_length=64),
) -> dict:
    service = get_service(request)
    try:
        return service.memory_entries(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/memory/weak")
def mark_weak_point(payload: WeakPointRequest, request: Request) -> dict:
    service = get_service(request)
    try:
        return service.mark_weak_point(payload.session_id, payload.topic, payload.detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MemoryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/memory/note")
def remember_note(payload: NoteRequest, request: Request) -> dict:
    service = get_service(request)
    try:
        return service.remember_note(payload.session_id, payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MemoryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/review-plan")
def review_plan(payload: PlanRequest, request: Request) -> dict:
    service = get_service(request)
    try:
        return service.review_plan(payload.session_id, payload.course)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/history")
def history(
    request: Request,
    session_id: str = Query(default="demo", max_length=64),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    service = get_service(request)
    try:
        return {"history": service.history(session_id, limit)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


WEB_DIR = Path(__file__).resolve().parents[2] / "web"
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


if __name__ == "__main__":
    uvicorn.run("reviewmate.api:app", host="127.0.0.1", port=8090, reload=False)
