import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

# The database is one file, stored next to main.py. SQLite creates it automatically.
DB_FILE = Path(__file__).parent / "tasks.db"

SEED_TASKS = [
    {"id": 1, "title": "Learn HTTP", "done": True},
    {"id": 2, "title": "Build a CRUD API", "done": False},
    {"id": 3, "title": "Publish to GitHub", "done": False},
]


# ---------- Stage 0: SQLite setup ----------
@contextmanager
def db():
    """Open a connection, commit on success, roll back on error, always close."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  # lets us read columns by name: row["title"]
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def seed_tasks(conn):
    conn.executemany(
        "INSERT INTO tasks (title, done) VALUES (?, ?)",
        [(t["title"], int(t["done"])) for t in SEED_TASKS],
    )


def init_db():
    with db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tasks (
                   id    INTEGER PRIMARY KEY,
                   title TEXT NOT NULL,
                   done  INTEGER NOT NULL DEFAULT 0
               )"""
        )
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        if count == 0:  # seed only on the very first run
            seed_tasks(conn)  # runs in one transaction: all 3 rows or none


def row_to_task(row):
    return {"id": row["id"], "title": row["title"], "done": bool(row["done"])}


@asynccontextmanager
async def lifespan(app):
    init_db()  # runs once every time the server starts
    yield


app = FastAPI(title="Task API", version="1.0", description="A CRUD API for a to-do list, stored in SQLite.", lifespan=lifespan)

# ---------- Old in-memory list (replaced step by step in Stages 1-3) ----------
tasks = [dict(t) for t in SEED_TASKS]


def find_task(task_id: int):
    return next((t for t in tasks if t["id"] == task_id), None)


def next_id() -> int:
    return max((t["id"] for t in tasks), default=0) + 1


# ---------- Request bodies ----------
class TaskCreate(BaseModel):
    title: str


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    done: Optional[bool] = None


# ---------- Errors: always JSON like {"error": "..."} ----------
@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    first = exc.errors()[0]
    field = ".".join(str(p) for p in first["loc"] if p != "body") or "body"
    return JSONResponse(status_code=400, content={"error": f"Invalid {field}: {first['msg']}"})


def bad_request(message: str):
    return JSONResponse(status_code=400, content={"error": message})


def not_found(task_id: int):
    return JSONResponse(status_code=404, content={"error": f"Task {task_id} not found"})


@app.get("/", summary="API description")
def root():
    return {"name": "Task API", "version": "1.0", "endpoints": ["/tasks"]}


@app.get("/health", summary="Health check")
def health():
    return {"status": "ok"}


# ---------- Read (in memory) ----------
@app.get("/tasks", summary="List all tasks (optional ?done= and ?search= filters)")
def list_tasks(done: Optional[bool] = None, search: Optional[str] = None):
    result = tasks
    if done is not None:
        result = [t for t in result if t["done"] == done]
    if search:
        result = [t for t in result if search.lower() in t["title"].lower()]
    return result


@app.get("/tasks/{task_id}", summary="Get one task by id")
def get_task(task_id: int):
    task = find_task(task_id)
    return task if task else not_found(task_id)


# ---------- Create (in memory) ----------
@app.post("/tasks", status_code=201, summary="Create a task")
def create_task(body: TaskCreate):
    title = body.title.strip()
    if not title:
        return bad_request("title must not be empty")
    task = {"id": next_id(), "title": title, "done": False}
    tasks.append(task)
    return task


# ---------- Update and delete (in memory) ----------
@app.put("/tasks/{task_id}", summary="Update a task's title and/or done")
def update_task(task_id: int, body: TaskUpdate):
    task = find_task(task_id)
    if not task:
        return not_found(task_id)
    if body.title is None and body.done is None:
        return bad_request("Provide at least one of: title, done")
    if body.title is not None:
        if not body.title.strip():
            return bad_request("title must not be empty")
        task["title"] = body.title.strip()
    if body.done is not None:
        task["done"] = body.done
    return task


@app.delete("/tasks/{task_id}", status_code=204, summary="Delete a task")
def delete_task(task_id: int):
    task = find_task(task_id)
    if not task:
        return not_found(task_id)
    tasks.remove(task)
    return Response(status_code=204)


# ---------- Extras (in memory) ----------
@app.get("/stats", summary="Task counts")
def stats():
    done = sum(1 for t in tasks if t["done"])
    return {"total": len(tasks), "done": done, "open": len(tasks) - done}


@app.post("/reset", summary="Restore the 3 starter tasks")
def reset():
    tasks[:] = [dict(t) for t in SEED_TASKS]
    return {"status": "reset", "total": len(tasks)}
