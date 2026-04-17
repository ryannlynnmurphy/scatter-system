#!/usr/bin/env python3
"""
Scatter Studio — Teaching Engine v0.1.0

Applies the Three-Tier Content Routing architecture (patent pending)
to project-based learning. Instead of K-8 curriculum subjects,
content is organized around PROJECTS people want to build.

The Scatter Method is the pedagogy:
- When a student faces a real decision, present the tradeoff (dialectic)
- Don't build it FOR them — build it WITH them
- Every decision is a learning moment
- The friction is the teaching

Three-Tier Routing (adapted for projects):
  Tier 1: Verified tutorial step from local database (fastest, most reliable)
  Tier 2: Existing step adapted to student's skill level (AI-assisted)
  Tier 3: Novel step generated with RAG context (AI-generated, verified)

Verification pipeline ensures no hallucinated instructions reach the student.
The system gets smarter over time as Tier 3 content promotes to Tier 1.
"""

import json
import os
import sqlite3
import datetime
from pathlib import Path
from urllib.request import Request, urlopen

OLLAMA_URL = os.environ.get("SCATTER_OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("SCATTER_MODEL", "qwen2.5-coder:7b")
FAST_MODEL = os.environ.get("SCATTER_FAST_MODEL", "llama3.2:3b")
DB_PATH = os.path.expanduser("~/.scatter/studio.db")

# ── Project Templates ──────────────────────────────────────────────────────
# These are the starting points. Each project is a sequence of steps,
# each step is a decision point where the student learns by building.

PROJECTS = {
    "chatbot": {
        "id": "chatbot",
        "title": "Build a Local AI Chatbot",
        "description": "Create an AI assistant that runs on your computer. No cloud. No subscription. Yours.",
        "difficulty": "beginner",
        "time_estimate": "2-4 hours",
        "prerequisites": [],
        "skills_learned": ["command line basics", "Ollama", "Python basics", "API concepts", "local inference"],
        "steps": [
            {
                "id": "chatbot-01",
                "title": "What is a language model?",
                "type": "concept",
                "content": "Before we build anything, let's understand what we're working with. A language model is a program that predicts what word comes next. That's it. When you type 'the cat sat on the', it predicts 'mat' because it's seen that pattern millions of times in books. Everything else — conversations, code generation, creative writing — emerges from that one ability: predicting the next word. The model running on your computer right now (the one helping you through this tutorial) works exactly this way.",
                "dialectic": {
                    "decision": None,
                    "tradeoff": None,
                },
                "artifact": None,
            },
            {
                "id": "chatbot-02",
                "title": "Open your terminal",
                "type": "action",
                "content": "Press Ctrl+Alt+T to open a terminal. This is where you talk to your computer directly. Everything you build in this project starts here. Type 'ollama list' and press Enter. You should see the models installed on your machine.",
                "verification": "ollama list",
                "success_pattern": "NAME",
                "dialectic": None,
                "artifact": None,
            },
            {
                "id": "chatbot-03",
                "title": "Your first conversation with a local model",
                "type": "action",
                "content": "Type: ollama run llama3.2:3b\n\nThis loads the 3B parameter model into your computer's memory and opens a conversation. Try asking it something. Notice the speed — this is running on YOUR hardware. No internet needed. When you're done, type /bye to exit.",
                "verification": None,
                "dialectic": None,
                "artifact": None,
            },
            {
                "id": "chatbot-04",
                "title": "Decision: Which programming language?",
                "type": "decision",
                "content": "Now we're going to write code that talks to the model programmatically — not through the chat interface, but through an API. You need to choose a language.",
                "dialectic": {
                    "thesis": "Python. It's the most common language for AI work. Huge ecosystem. Easy to read. Most tutorials use it.",
                    "antithesis": "JavaScript/Node.js. It's what the web runs on. If you ever want your chatbot to have a web interface, you're already in the right language. Also, you might already know some JS from browsing the web.",
                    "synthesis": "For a local chatbot, Python is the right choice. The AI ecosystem (Ollama's Python library, data processing, model tools) is overwhelmingly Python. You can add a web interface later — but the brain should be Python. If this were a web-first project, the answer would be different.",
                    "decision_prompt": "Which do you want to use? Python or JavaScript? (There's no wrong answer — I'll teach you either one.)",
                },
                "artifact": None,
            },
            {
                "id": "chatbot-05",
                "title": "Write your first API call",
                "type": "build",
                "content": "Create a file called chatbot.py. This is the brain of your chatbot. We're going to write a program that sends a message to your local model and prints the response.",
                "code_template": """# chatbot.py — Your first local AI chatbot
# This talks to Ollama running on your machine

import json
from urllib.request import Request, urlopen

OLLAMA_URL = "http://localhost:11434"
MODEL = "llama3.2:3b"

def ask(question):
    \"\"\"Send a question to your local model and get a response.\"\"\"
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": question}],
        "stream": False,
    }
    data = json.dumps(payload).encode()
    req = Request(
        f"{OLLAMA_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    return result["message"]["content"]

# Try it!
print("Your chatbot is thinking...")
answer = ask("What is the meaning of life? Answer in one sentence.")
print(f"Chatbot says: {answer}")
""",
                "dialectic": None,
                "artifact": "chatbot.py",
            },
            {
                "id": "chatbot-06",
                "title": "Decision: How should your chatbot remember?",
                "type": "decision",
                "content": "Right now your chatbot forgets everything between messages. Each question starts fresh. Real conversations have memory. How should we add it?",
                "dialectic": {
                    "thesis": "Keep messages in a Python list. Simple. Each message gets appended. Send the whole list to the model every time. The model sees the full conversation and can refer back.",
                    "antithesis": "The list grows forever. After 50 messages, you're sending thousands of tokens to the model every turn. On your hardware, this will slow to a crawl. Also, if you close the program, the memory is gone.",
                    "synthesis": "Start with the list — it's the simplest thing that works. Add a limit: keep the last 20 messages. Later, we'll add SQLite for permanent memory. But the simple version teaches you how conversation context actually works in AI systems.",
                    "decision_prompt": "Should we start simple (list in memory, lost when you close) or go straight to persistent storage (SQLite, survives restarts)? Simple teaches you the concept. Persistent teaches you databases.",
                },
                "artifact": None,
            },
            {
                "id": "chatbot-07",
                "title": "Make it conversational",
                "type": "build",
                "content": "Let's turn your single-question script into an actual conversation. A loop that keeps asking for input, sends it to the model with history, and prints the response.",
                "code_template": """# chatbot.py — Now with conversation memory
import json
from urllib.request import Request, urlopen

OLLAMA_URL = "http://localhost:11434"
MODEL = "llama3.2:3b"

def chat(messages):
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": 4096},
    }
    data = json.dumps(payload).encode()
    req = Request(f"{OLLAMA_URL}/api/chat", data=data,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    return result["message"]["content"]

# Conversation loop
history = [
    {"role": "system", "content": "You are a helpful assistant running locally. Be concise."}
]

print("Your chatbot is ready. Type 'quit' to exit.\\n")

while True:
    user_input = input("You: ").strip()
    if not user_input or user_input.lower() in ("quit", "exit"):
        print("Goodbye!")
        break

    history.append({"role": "user", "content": user_input})

    # Keep only last 20 messages (+ system prompt)
    if len(history) > 21:
        history = [history[0]] + history[-20:]

    response = chat(history)
    history.append({"role": "assistant", "content": response})
    print(f"Bot: {response}\\n")
""",
                "dialectic": None,
                "artifact": "chatbot.py",
            },
        ],
    },
    "website": {
        "id": "website",
        "title": "Build Your Personal Website",
        "description": "Create a website that's yours. Not on someone else's platform. Yours.",
        "difficulty": "beginner",
        "time_estimate": "1-2 hours",
        "prerequisites": [],
        "skills_learned": ["HTML", "CSS", "local file serving", "web fundamentals"],
        "steps": [],  # To be populated
    },
    "game": {
        "id": "game",
        "title": "Build a Browser Game",
        "description": "Make a game people can play in their browser. Canvas, animation, input handling.",
        "difficulty": "beginner",
        "time_estimate": "2-3 hours",
        "prerequisites": ["website"],
        "skills_learned": ["JavaScript", "Canvas API", "game loops", "collision detection"],
        "steps": [],  # To be populated
    },
    "voice-assistant": {
        "id": "voice-assistant",
        "title": "Build a Voice Assistant",
        "description": "Make your computer listen and talk. Speech-to-text, AI brain, text-to-speech.",
        "difficulty": "intermediate",
        "time_estimate": "4-6 hours",
        "prerequisites": ["chatbot"],
        "skills_learned": ["Whisper STT", "TTS", "audio processing", "service architecture"],
        "steps": [],  # To be populated
    },
    "home-server": {
        "id": "home-server",
        "title": "Set Up Your Own Server",
        "description": "Turn a computer into a server. Linux basics, networking, services.",
        "difficulty": "intermediate",
        "time_estimate": "3-5 hours",
        "prerequisites": ["chatbot"],
        "skills_learned": ["Linux", "systemd", "networking", "SSH", "security basics"],
        "steps": [],  # To be populated
    },
}


# ── Database ───────────────────────────────────────────────────────────────

def init_db():
    """Initialize the teaching database. Mirrors the patent's schema adapted for projects."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")

    db.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            difficulty TEXT,
            data JSON
        );

        CREATE TABLE IF NOT EXISTS steps (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            position INTEGER NOT NULL,
            title TEXT NOT NULL,
            type TEXT NOT NULL,
            content TEXT NOT NULL,
            code_template TEXT,
            dialectic JSON,
            verification TEXT,
            tier INTEGER DEFAULT 1,
            verified_at TEXT,
            UNIQUE(project_id, position)
        );

        CREATE TABLE IF NOT EXISTS learner (
            id INTEGER PRIMARY KEY DEFAULT 1,
            name TEXT,
            skill_level TEXT DEFAULT 'beginner',
            xp INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS progress (
            learner_id INTEGER DEFAULT 1,
            step_id TEXT NOT NULL,
            status TEXT DEFAULT 'not_started',
            completed_at TEXT,
            decision_made TEXT,
            notes TEXT,
            UNIQUE(learner_id, step_id)
        );

        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            learner_id INTEGER DEFAULT 1,
            step_id TEXT NOT NULL,
            thesis TEXT,
            antithesis TEXT,
            synthesis TEXT,
            choice TEXT,
            reasoning TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS steps_fts USING fts5(
            id, title, content, project_id
        );
    """)

    # Seed projects if empty
    existing = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    if existing == 0:
        for pid, project in PROJECTS.items():
            db.execute(
                "INSERT INTO projects (id, title, description, difficulty, data) VALUES (?, ?, ?, ?, ?)",
                (pid, project["title"], project["description"], project["difficulty"], json.dumps(project))
            )
            for i, step in enumerate(project.get("steps", [])):
                db.execute(
                    "INSERT INTO steps (id, project_id, position, title, type, content, code_template, dialectic, verification) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (step["id"], pid, i, step["title"], step["type"], step["content"],
                     step.get("code_template"), json.dumps(step.get("dialectic")), step.get("verification"))
                )
                # Index for search
                db.execute(
                    "INSERT INTO steps_fts (id, title, content, project_id) VALUES (?, ?, ?, ?)",
                    (step["id"], step["title"], step["content"], pid)
                )
        db.commit()

    return db


# ── Three-Tier Routing (adapted for projects) ─────────────────────────────

def route_request(db, topic, skill_level="beginner"):
    """
    Three-tier content routing adapted for project-based learning.
    Patent-pending architecture applied to a new domain.

    Tier 1: Verified step exists in database → serve directly
    Tier 2: Related step exists but needs adaptation → AI adapts
    Tier 3: No matching content → AI generates with RAG context, then verifies
    """
    # Tier 1: Direct match via FTS5
    matches = db.execute(
        "SELECT s.id, s.title, s.content, s.code_template, s.dialectic, s.project_id "
        "FROM steps_fts fts JOIN steps s ON fts.id = s.id "
        "WHERE steps_fts MATCH ? ORDER BY rank LIMIT 5",
        (topic,)
    ).fetchall()

    if matches:
        best = matches[0]
        return {
            "tier": 1,
            "step_id": best[0],
            "title": best[1],
            "content": best[2],
            "code_template": best[3],
            "dialectic": json.loads(best[4]) if best[4] else None,
            "project_id": best[5],
        }

    # Tier 2: Broader search + adapt
    broad_matches = db.execute(
        "SELECT s.id, s.title, s.content, s.project_id "
        "FROM steps s WHERE s.content LIKE ? LIMIT 3",
        (f"%{topic.split()[0] if topic.split() else topic}%",)
    ).fetchall()

    if broad_matches:
        base = broad_matches[0]
        return {
            "tier": 2,
            "step_id": base[0],
            "base_content": base[2],
            "project_id": base[3],
            "needs_adaptation": True,
            "target_skill": skill_level,
        }

    # Tier 3: Generate with RAG context
    # Gather related content for grounding
    all_steps = db.execute(
        "SELECT title, content FROM steps ORDER BY RANDOM() LIMIT 5"
    ).fetchall()
    rag_context = "\n\n".join(f"## {s[0]}\n{s[1]}" for s in all_steps)

    return {
        "tier": 3,
        "topic": topic,
        "rag_context": rag_context,
        "needs_generation": True,
        "needs_verification": True,
    }


# ── Verification (from patent) ────────────────────────────────────────────

VERIFY_PROMPT = """You are a technical content reviewer for a learn-to-build platform.
Compare the generated tutorial step against the reference material.
Check for: factual errors, dangerous commands, missing safety warnings, unclear instructions.
Respond with JSON only:
{"score": <0-100>, "issues": [{"claim": "...", "correction": "...", "severity": "low|medium|high"}]}
If no issues: {"score": 90, "issues": []}"""


def verify_content(generated, reference, model=None):
    """Verify AI-generated content against reference material."""
    model = model or FAST_MODEL
    messages = [
        {"role": "system", "content": VERIFY_PROMPT},
        {"role": "user", "content": f"GENERATED CONTENT:\n{generated}\n\nREFERENCE MATERIAL:\n{reference}"}
    ]

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": 4096, "temperature": 0.1},
    }
    try:
        data = json.dumps(payload).encode()
        req = Request(f"{OLLAMA_URL}/api/chat", data=data,
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
        content = result.get("message", {}).get("content", "")
        # Try to parse JSON from response
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception:
        pass
    return {"score": 0, "issues": [{"claim": "Verification failed", "correction": "Could not verify", "severity": "high"}]}


# ── Public API ─────────────────────────────────────────────────────────────

def get_projects(db):
    """List available projects."""
    rows = db.execute("SELECT id, title, description, difficulty FROM projects").fetchall()
    return [{"id": r[0], "title": r[1], "description": r[2], "difficulty": r[3]} for r in rows]


def get_project_steps(db, project_id):
    """Get all steps for a project in order."""
    rows = db.execute(
        "SELECT id, title, type, content, code_template, dialectic, position "
        "FROM steps WHERE project_id = ? ORDER BY position",
        (project_id,)
    ).fetchall()
    return [{
        "id": r[0], "title": r[1], "type": r[2], "content": r[3],
        "code_template": r[4], "dialectic": json.loads(r[5]) if r[5] else None,
        "position": r[6],
    } for r in rows]


def get_learner_progress(db, project_id):
    """Get learner's progress through a project."""
    rows = db.execute(
        "SELECT p.step_id, p.status, p.decision_made "
        "FROM progress p JOIN steps s ON p.step_id = s.id "
        "WHERE s.project_id = ? ORDER BY s.position",
        (project_id,)
    ).fetchall()
    return {r[0]: {"status": r[1], "decision": r[2]} for r in rows}


def record_decision(db, step_id, thesis, antithesis, synthesis, choice, reasoning=""):
    """Record a dialectical decision — this is research data."""
    db.execute(
        "INSERT INTO decisions (step_id, thesis, antithesis, synthesis, choice, reasoning) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (step_id, thesis, antithesis, synthesis, choice, reasoning)
    )
    db.execute(
        "INSERT OR REPLACE INTO progress (step_id, status, decision_made, completed_at) "
        "VALUES (?, 'completed', ?, datetime('now'))",
        (step_id, choice)
    )
    db.commit()


def complete_step(db, step_id):
    """Mark a step as completed."""
    db.execute(
        "INSERT OR REPLACE INTO progress (step_id, status, completed_at) "
        "VALUES (?, 'completed', datetime('now'))",
        (step_id,)
    )
    # Award XP
    db.execute("UPDATE learner SET xp = xp + 50, updated_at = datetime('now') WHERE id = 1")
    db.commit()


if __name__ == "__main__":
    db = init_db()
    projects = get_projects(db)
    print(f"\nScatter Studio — {len(projects)} projects available:\n")
    for p in projects:
        steps = get_project_steps(db, p["id"])
        print(f"  [{p['difficulty']}] {p['title']}")
        print(f"  {p['description']}")
        print(f"  {len(steps)} steps")
        print()
    db.close()
