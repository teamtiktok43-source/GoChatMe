from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3
import os
import uuid

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

if not os.path.exists("uploads"):
    os.mkdir("uploads")

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

@app.get("/")
async def home():
    return FileResponse("static/index.html")

@app.get("/chat")
async def chat():
    return FileResponse("static/chat.html")


# DATABASE

conn = sqlite3.connect("chat.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users(
username TEXT PRIMARY KEY,
email TEXT,
phone TEXT,
password TEXT,
avatar TEXT,
online INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS messages(
id INTEGER PRIMARY KEY AUTOINCREMENT,
sender TEXT,
receiver TEXT,
message TEXT,
seen INTEGER DEFAULT 0
)
""")

conn.commit()

connections = {}

# MODELS

class RegisterData(BaseModel):
    username:str
    email:str
    phone:str
    password:str

class LoginData(BaseModel):
    username:str
    password:str

class ForgotData(BaseModel):
    username:str
    phone:str


# CHECK USERNAME

@app.get("/check_username")
def check_username(username:str):

    cursor.execute("SELECT username FROM users WHERE username=?", (username,))
    row = cursor.fetchone()

    if row:
        return {"available":False}

    return {"available":True}


# REGISTER

@app.post("/register")
async def register(data:RegisterData):

    cursor.execute("SELECT username FROM users WHERE username=?", (data.username,))
    exists = cursor.fetchone()

    if exists:
        return {"status":"user_exists"}

    cursor.execute("""
    INSERT INTO users(username,email,phone,password,avatar,online)
    VALUES(?,?,?,?,?,0)
    """,(
        data.username,
        data.email,
        data.phone,
        data.password,
        ""
    ))

    conn.commit()

    return {"status":"ok"}


# LOGIN

@app.post("/login")
async def login(data:LoginData):

    cursor.execute("""
    SELECT * FROM users
    WHERE username=? AND password=?
    """,(data.username,data.password))

    user = cursor.fetchone()

    if user:

        cursor.execute("""
        UPDATE users SET online=1 WHERE username=?
        """,(data.username,))

        conn.commit()

        return {"status":"ok"}

    return {"status":"error"}


# FORGOT PASSWORD

@app.post("/forgot")
async def forgot(data:ForgotData):

    cursor.execute("""
    SELECT password FROM users
    WHERE username=? AND phone=?
    """,(data.username,data.phone))

    row = cursor.fetchone()

    if row:
        return {"password":row[0]}

    return {"status":"not_found"}


# SEARCH USERS

@app.get("/search_users")
def search_users(q:str):

    cursor.execute("""
    SELECT username FROM users
    WHERE username LIKE ?
    LIMIT 10
    """,('%'+q+'%',))

    rows = cursor.fetchall()

    return [r[0] for r in rows]


# UPLOAD AVATAR

@app.post("/upload_avatar/{username}")
async def upload_avatar(username:str,file:UploadFile=File(...)):

    filename = str(uuid.uuid4())+"_"+file.filename

    path = "uploads/"+filename

    with open(path,"wb") as f:
        f.write(await file.read())

    cursor.execute("""
    UPDATE users SET avatar=? WHERE username=?
    """,(filename,username))

    conn.commit()

    return {"file":filename}


# USER STATUS

@app.get("/status")
def status(user:str):

    cursor.execute("""
    SELECT online FROM users WHERE username=?
    """,(user,))

    row = cursor.fetchone()

    if row and row[0]==1:
        return {"status":"online"}

    return {"status":"offline"}


# GET CHATS

@app.get("/chats")
def chats(user:str):

    cursor.execute("""
    SELECT DISTINCT
    CASE
        WHEN sender=? THEN receiver
        ELSE sender
    END
    FROM messages
    WHERE sender=? OR receiver=?
    """,(user,user,user))

    rows = cursor.fetchall()

    return [r[0] for r in rows]


# GET MESSAGES

@app.get("/messages")
def messages(user:str,friend:str):

    cursor.execute("""
    UPDATE messages SET seen=1
    WHERE receiver=? AND sender=?
    """,(user,friend))

    conn.commit()

    cursor.execute("""
    SELECT sender,message FROM messages
    WHERE (sender=? AND receiver=?)
    OR (sender=? AND receiver=?)
    ORDER BY id
    """,(user,friend,friend,user))

    rows = cursor.fetchall()

    return [f"{r[0]}: {r[1]}" for r in rows]


# WEBSOCKET

@app.websocket("/ws")
async def websocket(ws:WebSocket):

    await ws.accept()

    username = await ws.receive_text()

    connections[username] = ws

    try:

        while True:

            data = await ws.receive_text()

            if data.startswith("typing|"):

                _,sender,receiver = data.split("|")

                if receiver in connections:
                    await connections[receiver].send_text(data)

                continue

            sender,receiver,message = data.split("|",2)

            cursor.execute("""
            INSERT INTO messages(sender,receiver,message)
            VALUES(?,?,?)
            """,(sender,receiver,message))

            conn.commit()

            if receiver in connections:
                await connections[receiver].send_text(data)

            await ws.send_text(data)

    except WebSocketDisconnect:

        if username in connections:
            del connections[username]

        cursor.execute("""
        UPDATE users SET online=0 WHERE username=?
        """,(username,))

        conn.commit()