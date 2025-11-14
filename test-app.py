import os
import json
import random
import streamlit as st
from datetime import datetime
import hashlib
from pymongo import MongoClient
import uuid


if "score" not in st.session_state:
    st.session_state["score"] = 0

if "questions_loaded" not in st.session_state:
    st.session_state["questions_loaded"] = []

if "answered" not in st.session_state:
    st.session_state["answered"] = []

if "choices" not in st.session_state:
    st.session_state["choices"] = []

if "feedback" not in st.session_state:
    st.session_state["feedback"] = []

if "q_index" not in st.session_state:
    st.session_state["q_index"] = 0

if "last_active" not in st.session_state:
    st.session_state["last_active"] = datetime.now()

if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())
    st.session_state["session_start"] = datetime.now()


# -----------------------------
# CSS
#------------------------------

st.markdown(
    """
    <style>
    .main-title {
        font-size: 24px;  /* change to whatever size you want */
        font-weight: 600;
        color: #1E90FF;
    }
    </style>
    """, unsafe_allow_html=True
)


# -----------------------------
# CONFIG
# -----------------------------
BASE_FOLDER = "subjects"
QUESTIONS_FILE_TYPES = [".txt", ".json"]

MONGO_URI = st.secrets["MONGO_URI"]
DB_NAME = st.secrets["DB_NAME"]  # <--- ADD THIS
client = MongoClient(MONGO_URI)

# Electricity / power / NETA Level 2 themed fun names
ELECTRIC_NAMES = [
    "Circuit Wizard", "Voltage Viking", "Amp Ace", "Ohm Explorer",
    "Current Commander", "Transformer Guru", "Power Surge",
    "Breaker Buddy", "Relay Ranger", "Capacitor Captain",
    "Generator Genius", "Insulator Hero", "Conductor Ninja",
    "Switch Master", "Load Lord", "Grid Guardian", "Watt Warrior",
    "Resistor Rider", "Fusible Friend", "Energy Eagle"
]

# -----------------------------
# MONGO CONNECTION
# -----------------------------
@st.cache_resource
def get_db():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    return db

db = get_db()
users_col = db["users"]
scores_col = db["scores"]

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------

def get_last_saved_score(user_id):
    record = scores_col.find_one({"user_id": user_id}, sort=[("timestamp", -1)])
    return int(record["score"]) if record else 0

def update_score(user_name, score_increment, total_questions_increment=0):
    """
    Add to the user's total score and total_questions instead of overwriting them.
    Creates a record if it doesn't exist yet.
    Also logs session info (unique session ID) in MongoDB.
    """
    timestamp = datetime.now()
    session_id = st.session_state.get("session_id")

    # --- Update scores collection ---
    scores_col.update_one(
        {"user_name": user_name, "session_id": session_id},
        {
            "$inc": {
                "score": score_increment,
                "total_questions": total_questions_increment
            },
            "$set": {
                "last_update": timestamp
            }
        },
        upsert=True
    )

    # --- Update Streamlit session cache ---
    if "scores_cache" not in st.session_state:
        st.session_state["scores_cache"] = []

# --- Update Streamlit cache ---
if "scores_cache" not in st.session_state:
    st.session_state["scores_cache"] = []

def load_scores_cache():
    if "scores_cache" not in st.session_state:
        st.session_state["scores_cache"] = list(scores_col.find())

def refresh_chat():
    """Fetch latest chat messages and store in session state."""
    st.session_state.chat_messages = get_messages()

# -----------------------------
# LAST ACTIVE HELPER
# -----------------------------
def update_last_active(user_id):
    """Update last_active timestamp in MongoDB and session_state."""
    now = datetime.now()
    st.session_state["last_active"] = now
    users_col.update_one({"user_id": user_id}, {"$set": {"last_active": now}})


# -----------------------------
# ONLINE STATUS HELPER
# -----------------------------
ONLINE_THRESHOLD_SECONDS = 120  # 2 minutes to be considered online

def is_user_online(user_doc):
    if not user_doc or "last_active" not in user_doc:
        return False
    last_seen = user_doc["last_active"]
    return (datetime.now() - last_seen).total_seconds() <= ONLINE_THRESHOLD_SECONDS


# -----------------------------
# STREAMLIT UI
# -----------------------------
st.set_page_config(page_title="NETA Practice Quiz", layout="wide")

if "user" not in st.session_state:
    st.session_state["user"] = None
if "last_active" not in st.session_state:
    st.session_state["last_active"] = datetime.now()

# -----------------------------
# AUTO-SET USER (no login)
# -----------------------------
if "user" not in st.session_state or st.session_state["user"] is None:
    random_name = random.choice(ELECTRIC_NAMES)
    st.session_state["user"] = f"Welcome, {random_name}!"
    st.session_state["score"] = 0
    st.session_state["questions_loaded"] = []
    st.session_state["total_questions"] = 0
    st.session_state["choices"] = []
    st.session_state["answered"] = []
    st.session_state["feedback"] = []
    st.session_state["q_index"] = 0
    st.session_state["last_active"] = datetime.now()


# -----------------------------
# QUIZ + CHAT SECTION
# -----------------------------
if st.session_state["user"]:
    st.session_state["last_active"] = datetime.now()
    user_name = st.session_state["user"]

    # -----------------------------
    # SINGLE FILE QUIZ SETUP
    # -----------------------------

    # Set your single subject folder and file here
    file_path = "NETA Level 2.json"  # just the file in the same folder

    questions = []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                questions = data
            elif isinstance(data, dict):
                for topic, qlist in data.items():
                    if isinstance(qlist, list):
                        questions.extend(qlist)
    except Exception as e:
        st.error(f"Failed to load {file_path}: {e}")

    # Shuffle questions
    random.shuffle(questions)

    # Save to session state if first load
    if "questions_loaded" not in st.session_state:
        st.session_state.questions_loaded = questions
        st.session_state.q_index = 0
        st.session_state.answered = [False] * len(questions)
        st.session_state.feedback = [""] * len(questions)
        st.session_state.choices = [None] * len(questions)

    questions = st.session_state.questions_loaded
    total_questions = len(questions)

    # -----------------------------
    # SIDEBAR (file name & stats)
    # -----------------------------
    st.sidebar.markdown("### 📘 Quiz Topic")

    # Hardcoded JSON file
    selected_file = "NETA Level 2.json"  # <-- same folder as the Python script
    file_display = os.path.splitext(selected_file)[0]  # removes .json

    # Display only the file name (without extension)
    st.sidebar.markdown(f"**{file_display}**")
    st.sidebar.markdown("---")

    # Placeholder for correct / wrong counts
    correct_count = sum(
        1 for i, ans in enumerate(st.session_state.choices)
        if ans == questions[i].get("answer") and st.session_state.answered[i]
    )
    wrong_count = sum(
        1 for i, ans in enumerate(st.session_state.choices)
        if ans != questions[i].get("answer") and st.session_state.answered[i]
    )
    st.sidebar.markdown(f"✅ Correct: {correct_count}")
    st.sidebar.markdown(f"❌ Wrong: {wrong_count}")

    # -----------------------------
    # LOAD QUESTIONS
    # -----------------------------
    st.markdown(f"### 👤 {user_name}<br>", unsafe_allow_html=True)

    def load_questions(path):
        questions = []

        def scan_folder(folder_path, level=0):
            indent = "&nbsp;" * (level * 4)

            # ✅ If it's a file, just try to load it directly
            if os.path.isfile(folder_path) and any(folder_path.endswith(ext) for ext in QUESTIONS_FILE_TYPES):
                try:
                    with open(folder_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        file_questions = []

                        if isinstance(data, list):
                            file_questions = data
                        elif isinstance(data, dict):
                            for topic, qlist in data.items():
                                if isinstance(qlist, list):
                                    file_questions.extend(qlist)

                        questions.extend(file_questions)
                        st.sidebar.markdown(
                            f"{indent}📄 {os.path.basename(folder_path)} — "
                            f"<span style='color:#1E90FF'>{len(file_questions)}</span> questions",
                            unsafe_allow_html=True
                        )
                except Exception as e:
                    st.warning(f"❌ Could not load {folder_path}: {e}")
                return  # ✅ Exit after processing a file

            # ✅ Otherwise, it’s a folder → scan inside it
            if os.path.isdir(folder_path):
                st.sidebar.markdown(f"{indent}📂 **{os.path.basename(folder_path)}/**")
                try:
                    for entry in os.listdir(folder_path):
                        scan_folder(os.path.join(folder_path, entry), level + 1)
                except Exception as e:
                    st.warning(f"❌ Could not access {folder_path}: {e}")
            else:
                st.warning(f"⚠️ Skipped non-file/non-folder: {folder_path}")

        # 🏁 Start recursive scan
        if os.path.exists(path):
            st.sidebar.markdown("### 🧩 Loaded Question Files")
            scan_folder(path)
        else:
            st.warning(f"Path not found: {path}")

        return questions


    def load_all_questions(base_folder="."):
        all_questions = []

        for root, _, files in os.walk(base_folder):
            for file in files:
                IGNORE_FILES = {"requirements.txt", "README.txt"}
                if any(file.endswith(ext) for ext in QUESTIONS_FILE_TYPES) and file not in IGNORE_FILES:

                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if isinstance(data, list):
                                all_questions.extend(data)
                            elif isinstance(data, dict):
                                for topic, qlist in data.items():
                                    if isinstance(qlist, list):
                                        all_questions.extend(qlist)
                    except Exception as e:
                        st.warning(f"❌ Could not load {file_path}: {e}")

        random.shuffle(all_questions)
        return all_questions


    if not st.session_state.get("questions_loaded"):
        st.session_state.questions_loaded = load_all_questions()
        random.shuffle(st.session_state.questions_loaded)
        st.session_state.q_index = 0
        st.session_state.answered = [False] * len(st.session_state.questions_loaded)
        st.session_state.feedback = [""] * len(st.session_state.questions_loaded)
        st.session_state.choices = [None] * len(st.session_state.questions_loaded)

    questions = st.session_state.questions_loaded
    total_questions = len(questions)

    # -----------------------------
    # NAVIGATION
    # -----------------------------
    if "nav_action" not in st.session_state:
        st.session_state.nav_action = None

    col = st.columns(1)[0]
    with col:
        if st.button("➡️ Next Question"):
            st.session_state.nav_action = "next"

    if st.session_state.nav_action == "prev" and st.session_state.q_index > 0:
        st.session_state.q_index -= 1
    elif st.session_state.nav_action == "next" and st.session_state.q_index < len(questions) - 1:
        st.session_state.q_index += 1
        update_last_active(user_name)

    st.session_state.nav_action = None

    # -----------------------------
    # LAYOUT: QUIZ + CHAT SIDE BY SIDE
    # -----------------------------
    col_main = st.container()

    # Scrollable container for questions
    with col_main:
        st.markdown("<div style='max-height:600px; overflow-y:auto; padding-right:5px;'>", unsafe_allow_html=True)
        if questions:
            current_q = questions[st.session_state.q_index]
            st.markdown(f"### Question {st.session_state.q_index + 1} of {len(questions)}")
            st.write(current_q.get("question", "No question text available."))

            options = current_q.get("options", [])
            if not options:
                st.error("Question has no options configured.")
            else:
                prev_choice = st.session_state.choices[st.session_state.q_index]
                disabled = st.session_state.answered[st.session_state.q_index]

                if prev_choice is not None and prev_choice in options:
                    choice = st.radio(
                        "Select an answer:", options, index=options.index(prev_choice), disabled=disabled
                    )
                else:
                    choice = st.radio("Select an answer:", options, index=None, disabled=disabled)

                if st.button("✅ Submit Answer"):
                    if not st.session_state.answered[st.session_state.q_index]:
                        st.session_state.choices[st.session_state.q_index] = choice
                        st.session_state.answered[st.session_state.q_index] = True
                        correct = choice == current_q.get("answer")
                        if correct:
                            st.session_state.score += 1
                            st.session_state.feedback[st.session_state.q_index] = (
                                f"✅ Correct!\n\nExplanation: {current_q.get('explanation', 'No explanation.')}"
                            )
                        else:
                            st.session_state.feedback[st.session_state.q_index] = (
                                f"❌ Wrong! Correct: {current_q.get('answer', 'N/A')}\n\n"
                                f"Explanation: {current_q.get('explanation', 'No explanation.')}"
                            )

                        # ✅ Update score and last active
                        update_score(user_name, 1 if correct else 0, 0)
                        update_last_active(user_name)

                        # Save the answer to MongoDB in a single session document
                        scores_col.update_one(
                            {"session_id": st.session_state["session_id"], "user_name": user_name},
                            {"$push": {
                                "answers": {
                                    "question_index": st.session_state.q_index,
                                    "question_text": current_q.get("question"),
                                    "selected_choice": choice,
                                    "correct": correct,
                                    "timestamp": datetime.now()
                                }
                            },
                                "$set": {"last_update": datetime.now()}},
                            upsert=True
                        )



                    else:
                        st.info("You already submitted this question. Click Next to continue.")

            # Check if user reached total questions
            if st.session_state.score >= total_questions:
                scores_col.update_many({}, {
                    "$set": {"score": 0, "total_questions": total_questions, "timestamp": datetime.now()}
                })

                st.session_state.score = 0
                st.session_state.answered = [False] * total_questions
                st.session_state.feedback = [""] * total_questions
                st.session_state.choices = [None] * total_questions
                st.session_state.q_index = 0

                st.success("🎉 Maximum score reached. All scores have been reset to 0. Start again!")

            if st.session_state.answered[st.session_state.q_index]:
                st.info(st.session_state.feedback[st.session_state.q_index])

        st.markdown("</div>", unsafe_allow_html=True)