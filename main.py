from typing import Optional

from fastapi import FastAPI, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

app = FastAPI(title="Task API", version="1.0", description="A small in-memory CRUD API for a to-do list.")

# ---------- Stage 2: in-memory "database" ----------
SEED_TASKS = [
    {"id": 1, "title": "Learn HTTP", "done": True},
    {"id": 2, "title": "Build a CRUD API", "done": False},
    {"id": 3, "title": "Publish to GitHub", "done": False},
]
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
    # FastAPI defaults to 422; the assignment wants 400 Bad Request.
    first = exc.errors()[0]
    field = ".".join(str(p) for p in first["loc"] if p != "body") or "body"
    return JSONResponse(status_code=400, content={"error": f"Invalid {field}: {first['msg']}"})


def bad_request(message: str):
    return JSONResponse(status_code=400, content={"error": message})


def not_found(task_id: int):
    return JSONResponse(status_code=404, content={"error": f"Task {task_id} not found"})


# ---------- Stage 1: root and health ----------
@app.get("/", summary="API description")
def root():
    return {"name": "Task API", "version": "1.0", "endpoints": ["/tasks"]}


@app.get("/health", summary="Health check")
def health():
    return {"status": "ok"}


# ---------- Stage 2: read ----------
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


# ---------- Stage 3: create ----------
@app.post("/tasks", status_code=201, summary="Create a task")
def create_task(body: TaskCreate):
    title = body.title.strip()
    if not title:
        return bad_request("title must not be empty")
    task = {"id": next_id(), "title": title, "done": False}
    tasks.append(task)
    return task


# ---------- Stage 4: update and delete ----------
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


# ---------- Extras (optional) ----------
@app.get("/stats", summary="Task counts")
def stats():
    done = sum(1 for t in tasks if t["done"])
    return {"total": len(tasks), "done": done, "open": len(tasks) - done}


@app.post("/reset", summary="Restore the 3 seed tasks")
def reset():
    tasks[:] = [dict(t) for t in SEED_TASKS]
    return {"status": "reset", "total": len(tasks)}
