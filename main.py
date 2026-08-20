import os
import json
import requests
from datetime import date
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from typing import Optional
from openai import OpenAI
from typing import List
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows your browser to talk to the VM IP
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# --- 1. CONFIGURATION & STATE ---
### base_url="https://api.scaleway.ai/6fe13c19-2d47-43ff-ac2f-ef858418a2b5/v1",
SCALEWAY_API_KEY = os.getenv("SCALEWAY_API_KEY")
if not SCALEWAY_API_KEY:
    raise ValueError("SCALEWAY_API_KEY environment variable is required")

SCALEWAY_BASE_URL = os.getenv("SCALEWAY_BASE_URL")

client = OpenAI(
	api_key=SCALEWAY_API_KEY,
    	base_url=SCALEWAY_BASE_URL
    	)

TODO_API_URL = "http://127.0.0.1:8000" # Internal communication

# --- 2. THE TOOLS DEFINITION ---
tools = [
    {
        "type": "function",
        "function": {
            "name": "add_todo",
            "description": "Add a new todo item to the list",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The description of the task"},
		    "due_date": {"type": "string", "description": "The due date in YYYY-MM-DD format"}
                },
		 "required": ["task"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_todos",
            "description": "Retrieve the current list of todo items including their IDs, status, and due date.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_todo",
            "description": "Delete a task by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {"type": "integer"}
                },
                "required": ["todo_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_todo",
            "description": "Modify an existing task's name or due date using its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {"type": "integer", "description": "The ID of the task to update"},
                    "task": {"type": "string", "description": "The new description for the task"},
                    "due_date": {"type": "string", "description": "The new due date in YYYY-MM-DD format"}
                },
                "required": ["todo_id", "task"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "toggle_todo",
            "description": "Toggle the completion status of a task by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {"type": "integer"}
                },
                "required": ["todo_id"]
            	}
            }
    	}
    ]

# Database connection settings (Using your Scaleway Private IP)
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT", "5432"),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASS")
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
# --- 3. THE CRUD ENDPOINTS (The "Body") ---

def internal_add_todo(task, due_date=None): #This is C (create) in CRUD
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    try:
        if due_date:
            cur.execute("INSERT INTO todos (task, due_date) VALUES (%s, %s) RETURNING id;", (task, due_date))
        else:
            cur.execute("INSERT INTO todos (task) VALUES (%s) RETURNING id;", (task,))
        
        new_id = cur.fetchone()[0]
        conn.commit()
        return f"Created task with ID {new_id}"
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()

def internal_get_todos(): #This is the R (Read) in CRUD
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM todos ORDER BY id ASC;")
    todos = cur.fetchall()
    cur.close()
    conn.close()
    # Convert rows to a list of dicts so the AI can read it as JSON
    return json.dumps([dict(todo) for todo in todos], default=str)

def internal_update_todo(todo_id, task=None, due_date=None, completed=None): #This is the U (Update) in CRUD
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    # Dynamically build the update query based on what the AI provided
    if completed is not None:
        cur.execute("UPDATE todos SET completed = %s WHERE id = %s;", (completed, todo_id))
    if task:
        cur.execute("UPDATE todos SET task = %s WHERE id = %s;", (task, todo_id))
    if due_date:
        cur.execute("UPDATE todos SET due_date = %s WHERE id = %s;", (due_date, todo_id))
    conn.commit()
    cur.close()
    conn.close()
    return f"Successfully updated task ID {todo_id}."

def internal_delete_todo(todo_id): #This is the D (Delete) in CRUD
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("DELETE FROM todos WHERE id = %s;", (todo_id,))
    conn.commit()
    cur.close()
    conn.close()
    return f"Successfully deleted task ID {todo_id}."



@app.get("/todos")
async def get_todos():
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
async def create_todo(todo: TodoCreate):
    try:
        # Call the internal function the AI uses
        result_msg = internal_add_todo(todo.task, todo.due_date)
        return {"message": "Created", "detail": result_msg}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/todos/{todo_id}")
async def delete_todo(todo_id: int):
    """Remove a task by its ID"""
    result = internal_delete_todo(todo_id)
    return {"message": result}

@app.patch("/todos/{todo_id}/toggle")
async def toggle_todo(todo_id: int):
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
async def update_todo(todo_id: int, todo: TodoCreate):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute(
        "UPDATE todos SET task = %s, due_date = %s WHERE id = %s;",
        (todo.task, todo.due_date, todo_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Updated"}

from fastapi.responses import FileResponse

# The index.html web page
# ROUTE 1: The Main Dashboard (The Frame)
@app.get("/",response_class=HTMLResponse)
async def read_index():
    return FileResponse('index.html')


# ROUTE 2: Produce an HTML Table
@app.get("/table", response_class=HTMLResponse)
async def get_table():
    # 1. Get the latest data from the DB
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT * FROM todos ORDER BY id ASC;")
    todos = cur.fetchall()
    print(f"DEBUG: Database returned {len(todos)} rows.") # Check your docker logs for this!
    cur.close()
    conn.close()
    # 2. Build the HTML string (The same headers you have now)
    table_html = """
    <link rel="stylesheet" href="/static/style.css">
    <table>
        <thead>
        <style>
            body {
                margin: 0;
                font-family: sans-serif;
                /* This ensures the scrollbar is always visible or at least functional */
                overflow-y: auto; 
            }
            table {
                width: 100%;
                border-collapse: collapse;
                table-layout: auto; /* Allows columns to adjust to content */
            }
            /* The "Action" column needs extra width for 3 buttons */
            td:last-child {
                white-space: nowrap; /* Prevents buttons from wrapping to a new line */
                width: 250px;       /* Gives them enough breathing room */
                text-align: center;
            }
            th, td {
                border-bottom: 1px solid #ddd;
                padding: 8px;
                text-align: left;
            }
            button {
                margin-right: 4px;
                cursor: pointer;
            }
        </style>
            <tr>
                <th>ID</th>
                <th>Done</th>
                <th>Task</th>
                <th>Due Date</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
    """
    for todo in todos:
        todo_id = todo['id']
        task_text = todo['task']
        status = "✅" if todo['completed'] else "❌"
        toggle_label = "Undone" if todo['completed'] else "Done"
        due_date = todo.get('due_date') or ''
    
        table_html += f"""
            <tr>
                <td>{todo_id}</td>
                <td>{status}</td>
                <td>{task_text}</td>
                <td>{due_date}</td>
                <td>
                    <button onclick="window.parent.deleteTask({todo_id})">Delete</button>
                    <button onclick="window.parent.toggleTask({todo_id})">{toggle_label}</button>
		    <button onclick="window.parent.editTask({todo_id},'{task_text}','{due_date}')">Modify</button>
                </td>
            </tr>
        """

    table_html += "</tbody></table>"
    return table_html

# --- 4. THE CHAT ENDPOINT (The "Brain") ---
@app.post("/chat")
async def chat_endpoint(request: Request):  
    from datetime import datetime
    data = await request.json()
    user_input = data.get("message")

    # Get today's date so AI can calculate relative dates correctly
    today = datetime.now().strftime("%A, %Y-%m-%d")


    # BRAKE 1: Fresh history for every request
    local_messages = [
        {"role": "system", "content": "You are a concise To-Do manager. If you need to update or delete a task but don't know the ID, call get_todos first to find it. If the user doesn't say or imply that they are talking about the task list, respond as a helpful assistant. IMPORTANT: You must call 'get_todos' before updating or deleting to ensure you have the correct ID. If a task is not in the list, inform the user you cannot find it."},
	{"role": "user", "content": f"Today's date is {today}. {user_input}"}]
    local_messages.append({"role": "user", "content": user_input})

    try:
        # Initial call
        response = client.chat.completions.create(
            model="llama-3.3-70b-instruct",
            messages=local_messages,
            tools=tools
        )
        max_iterations = 7  # BRAKE 3: Prevent infinite loops
        iterations = 0

        # 2. Process tool calls (like add_todo, delete_todo)
        while response.choices[0].message.tool_calls and iterations < max_iterations:
            iterations += 1
            response_message = response.choices[0].message
            local_messages.append(response_message)

            for tool_call in response_message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                # BRAKE 2: Direct internal execution
                if name == "get_todos":
                    result = internal_get_todos()

                elif name == "add_todo":
                    result = internal_add_todo(args.get("task"), args.get("due_date"))

                elif name == "delete_todo":
                    result =  internal_delete_todo(args.get("todo_id"))
                
                elif name == "update_todo":
                    result = internal_update_todo(
                        todo_id=args.get("todo_id"),
                        task=args.get("task"),
                        due_date=args.get("due_date"),
                        completed=args.get("completed")
                    )
                
                else:
                    result = "Unknown tool"

                # Append the string result back to the conversation
                local_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": name,
                    "content": result
                })
            # Get the AI's reaction to the tool result
            response = client.chat.completions.create(
                model="llama-3.3-70b-instruct",
                messages=local_messages,
                tools=tools
            )

        final_content = response.choices[0].message.content
        return {"reply": final_content, "refresh_needed": True}

    except Exception as e:
        print(f"CRITICAL CHAT ERROR: {e}")
        return {"reply": f"Sorry, I ran into an error: {str(e)}", "refresh_needed": False}



# This tells FastAPI to serve files from the current directory
app.mount("/static", StaticFiles(directory="."), name="static")
