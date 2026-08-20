import os
from datetime import date
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from typing import Optional

app = FastAPI()
# This tells FastAPI to serve files from the current directory
app.mount("/static", StaticFiles(directory="."), name="static")

# Database connection settings (Using your Scaleway Private IP)
DB_CONFIG = {
    "host": os.getenv("DB_HOST","172.16.8.3"), 
    "database": os.getenv("DB_NAME","todolist"),
    "user": os.getenv("DB_USER","admin_user"),
    "password": os.getenv("DB_PASS", "fallback_password")
}

# This defines the "shape" of the data the user sends us via JSON
class Todo(BaseModel):
    id: int
    task: str
    due_date: Optional[date]
    completed: bool

class TodoCreate(BaseModel):
    task: str
    due_date: Optional[date] = None

# --- ROUTES ---

@app.get("/todos")
def get_todos():
    """Fetch all tasks from the DB"""
    conn = psycopg2.connect(**DB_CONFIG)
    # RealDictCursor returns results as Python dicts instead of tuples
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, task, due_date, completed FROM todos ORDER BY id ASC;")
    results = cur.fetchall()
    cur.close()
    conn.close()
    return results

@app.post("/todos")
def create_todo(todo: TodoCreate):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    # Check if a date was actually provided
    if todo.due_date:
        # If we have a date, include it in the INSERT
        query = "INSERT INTO todos (task, due_date) VALUES (%s, %s) RETURNING id;"
        params = (todo.task, todo.due_date)
    else:
        # If no date (None/Null), omit it so Postgres uses the DEFAULT
        query = "INSERT INTO todos (task) VALUES (%s) RETURNING id;"
        params = (todo.task,)

    try:
        cur.execute(query, params)
        new_id = cur.fetchone()[0]
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()
        conn.close()
    return {"message": "Created", "id": new_id}

@app.delete("/todos/{todo_id}")
def delete_todo(todo_id: int):
    """Remove a task by its ID"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("DELETE FROM todos WHERE id = %s;", (todo_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "deleted", "id": todo_id}

@app.patch("/todos/{todo_id}/toggle")
def toggle_todo(todo_id: int):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    # Flip the boolean value in the DB
    cur.execute(
        "UPDATE todos SET completed = NOT completed WHERE id = %s RETURNING completed;", 
        (todo_id,)
    )
    new_status = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"id": todo_id, "completed": new_status}

@app.put("/todos/{todo_id}")
def update_todo(todo_id: int, todo: TodoCreate):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute(
        "UPDATE todos SET task = %s, due_date = %s  WHERE id = %s;",
        (todo.task, todo.due_date, todo_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Updated task and date"}

from fastapi.responses import FileResponse

@app.get("/")
def read_index():
    return FileResponse('index.html')
