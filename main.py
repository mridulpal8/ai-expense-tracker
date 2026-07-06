from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
import sqlite3
import hashlib  # <-- Password hashing ke liye
from pydantic import BaseModel
from groq import Groq

# 1. Sabse pehle 'app' ko define karna compulsory hai (Isi wajah se error aaya tha)
app = FastAPI()

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# 🔑 Apni active Groq key yahan daalna
# 🔑 Apni API key yahan se mita kar khaali chor do, taaki GitHub accept karle
client = Groq(api_key="YOUR_GROQ_API_KEY_HERE")

# Models ke structures
class UserText(BaseModel):
    text: str
    username: str

class AuthModel(BaseModel):
    username: str
    password: str

def get_db_connection():
    return sqlite3.connect('finance.db')

# 🛠️ Database Tables Initialisation
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS my_expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, item TEXT, amount INTEGER, category TEXT)''')
    conn.commit()
    conn.close()

init_db()

# 🔐 PASSWORD HASH KARNE KA FUNCTION
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# 🔐 SIGNUP ENDPOINT
@app.post("/signup")
async def signup(auth: AuthModel):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        hashed_pass = hash_password(auth.password)
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (auth.username, hashed_pass))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Username pehle se exist karta hai!")
    conn.close()
    return {"status": "success", "message": "Signup successful!"}

# 🔑 LOGIN ENDPOINT
@app.post("/login")
async def login(auth: AuthModel):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username = ?", (auth.username,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0] == hash_password(auth.password):
        return {"status": "success", "message": "Login successful!"}
    raise HTTPException(status_code=401, detail="Galat Username ya Password!")

# 🛍️ ADD EXPENSE
# 🛍️ ADD EXPENSE (Upgraded with robust error handling)
@app.post("/add-expense")
async def add_expense(user_input: UserText):
    print(f"📥 Frontend se text aaya: {user_input.text}")
    
    if not user_input.text.strip():
        raise HTTPException(status_code=400, detail="Text khali nahi hona chahiye!")

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "User ke text se expenses nikaalein aur is JSON format me dein: {\"expenses\": [{\"item\": \"string\", \"amount\": 100, \"category\": \"string\"}]}"},
                {"role": "user", "content": user_input.text}
            ],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"}
        )
        
        # AI ke response ko parse karna
        raw_content = chat_completion.choices[0].message.content
        json_data = json.loads(raw_content)
        
    except json.JSONDecodeError:
        # Agar AI ne sahi JSON nahi diya
        print("❌ AI ne invalid JSON format diya!")
        raise HTTPException(status_code=502, detail="AI response format invalid tha, dobara try karein.")
    except Exception as e:
        # Baaki kisi bhi tarah ke network/API error ke liye
        print(f"❌ Groq API Error: {str(e)}")
        raise HTTPException(status_code=500, detail="AI server se connect nahi ho paya.")
    
    # Agar sab sahi hai, toh DB me save karo
    conn = get_db_connection()
    cursor = conn.cursor()
    saved_items = []
    
    try:
        for exp in json_data.get('expenses', []):
            # Edge case: Agar amount string me aa gaya ho toh use int me badlo
            amount = int(exp.get('amount', 0))
            item = exp.get('item', 'Unknown Item')
            category = exp.get('category', 'Others')
            
            cursor.execute(
                "INSERT INTO my_expenses (username, item, amount, category) VALUES (?, ?, ?, ?)", 
                (user_input.username, item, amount, category)
            )
            last_id = cursor.lastrowid
            saved_items.append({"id": last_id, "item": item, "amount": amount, "category": category})
            
        conn.commit()
    except Exception as db_err:
        print(f"❌ Database Error: {str(db_err)}")
        raise HTTPException(status_code=500, detail="Database me save karte waqt error aaya.")
    finally:
        conn.close()
        
    return {"status": "success", "data_saved": saved_items}