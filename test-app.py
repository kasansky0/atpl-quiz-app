import os
import json
import random
import streamlit as st
from datetime import datetime
import pandas as pd
import hashlib
from pymongo import MongoClient

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
SESSION_TIMEOUT_SECONDS = 300  # 5 minutes timeout

MONGO_URI = st.secrets["MONGO_URI"]
DB_NAME = st.secrets["DB_NAME"]  # <--- ADD THIS
client = MongoClient(MONGO_URI)



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
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(user_id, password):
    hashed = hash_password(password)
    if users_col.find_one({"user_id": user_id}):
        st.error("User ID already exists. Choose a different ID.")
        return False
    users_col.insert_one({
        "user_id": user_id,
        "hashed_password": hashed,
        "created_at": datetime.now()
    })
    st.success("✅ Registration successful! You can now log in.")
    return True

def verify_login(user_id, password):
    user = users_col.find_one({"user_id": user_id})
    if user and user.get("hashed_password") == hash_password(password):
        return True
    return False

def get_last_saved_score(user_id):
    record = scores_col.find_one({"user_id": user_id}, sort=[("timestamp", -1)])
    return int(record["score"]) if record else 0

def update_score(user_id, score, total_questions):
    timestamp = datetime.now()
    scores_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "score": score,
            "total_questions": total_questions,
            "timestamp": timestamp
        }},
        upsert=True
    )
    if "scores_cache" not in st.session_state:
        st.session_state["scores_cache"] = []
    st.session_state["scores_cache"] = [
        r for r in st.session_state["scores_cache"] if r.get("user_id") != user_id
    ]
    st.session_state["scores_cache"].append({"user_id": user_id, "score": score})

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
st.set_page_config(page_title="ATPL Practice Quiz", layout="wide")

if "user" not in st.session_state:
    st.session_state["user"] = None
if "last_active" not in st.session_state:
    st.session_state["last_active"] = datetime.now()

# -----------------------------
# SESSION TIMEOUT CHECK
# -----------------------------
if st.session_state["user"]:
    now = datetime.now()
    elapsed = (now - st.session_state["last_active"]).total_seconds()
    if elapsed > SESSION_TIMEOUT_SECONDS:
        st.session_state["user"] = None
        st.warning("⚠️ Session expired due to inactivity. Please log in again.")

# -----------------------------
# LOGIN / REGISTER
# -----------------------------
if st.session_state["user"] is None:
    st.subheader("Login or Register to Continue")
    auth_mode = st.radio("Choose action:", ["Login", "Register"])
    user_id = st.text_input("User ID")
    password = st.text_input("Password", type="password")
    if st.button("Submit"):
        if not user_id or not password:
            st.error("⚠️ Please enter both User ID and Password.")
        elif auth_mode == "Register":
            register_user(user_id, password)
        else:
            if verify_login(user_id, password):
                st.session_state["user"] = user_id

                # Reset score for this user
                st.session_state["score"] = 0
                update_score(user_id, 0, 0)  # reset score in MongoDB

                st.session_state["questions_loaded"] = []
                st.session_state["total_questions"] = 0
                st.session_state["choices"] = []
                st.session_state["answered"] = []
                st.session_state["feedback"] = []
                st.session_state["q_index"] = 0
                st.session_state["last_active"] = datetime.now()

                # ✅ Update last_active in MongoDB
                update_last_active(user_id)

                st.success(f"✅ Login successful! Welcome {user_id}. Your score has been reset.")
                st.rerun()


            else:
                st.error("❌ Invalid User ID or Password.")


# -----------------------------
# QUIZ + CHAT SECTION
# -----------------------------
if st.session_state["user"]:
    st.session_state["last_active"] = datetime.now()
    user_name = st.session_state["user"]

    # ======================================
    # 📂 SUBJECT & TOPIC SELECTOR (SIDEBAR)
    # ======================================

    st.sidebar.markdown("### 📘 Choose Subject and Topic")

    base_folder = BASE_FOLDER  # "subjects"

    try:
        subject_folders = [f for f in os.listdir(base_folder) if os.path.isdir(os.path.join(base_folder, f))]
    except Exception as e:
        st.sidebar.error(f"Could not access folder '{base_folder}': {e}")
        subject_folders = []

    if not subject_folders:
        st.sidebar.warning("⚠️ No subject folders found inside 'subjects/'.")
    else:
        selected_subject = st.sidebar.selectbox("Select Subject Folder:", subject_folders)

        subject_path = os.path.join(base_folder, selected_subject)
        available_files = [
            f for f in os.listdir(subject_path)
            if any(f.endswith(ext) for ext in QUESTIONS_FILE_TYPES)
        ]

        if available_files:
            selected_file = st.sidebar.selectbox("Select Topic File:", available_files)

            # ✅ Checkboxes for loading scope
            load_all_in_subject = st.sidebar.checkbox("📚 Load All Files in This Subject (Shuffle Every Time)")
            load_all_subjects = st.sidebar.checkbox("🌍 Load ALL JSON Files in ALL Subjects")

            questions = []

            # 🟥 Highest priority — load everything
            if load_all_subjects:
                st.sidebar.success("✅ Loading ALL questions from ALL subjects...")
                for root, _, files in os.walk(BASE_FOLDER):
                    for file_name in files:
                        if any(file_name.endswith(ext) for ext in QUESTIONS_FILE_TYPES):
                            file_path = os.path.join(root, file_name)
                            try:
                                with open(file_path, "r", encoding="utf-8") as f:
                                    data = json.load(f)
                                    if isinstance(data, list):
                                        questions.extend(data)
                                    elif isinstance(data, dict):
                                        for topic, qlist in data.items():
                                            if isinstance(qlist, list):
                                                questions.extend(qlist)
                            except Exception as e:
                                st.warning(f"⚠️ Could not load {file_name}: {e}")

                random.shuffle(questions)

            # 🟡 Medium priority — all files in selected subject
            elif load_all_in_subject:
                st.sidebar.success(f"✅ Loading all files from **{selected_subject}**...")
                for file_name in available_files:
                    file_path = os.path.join(subject_path, file_name)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if isinstance(data, list):
                                questions.extend(data)
                            elif isinstance(data, dict):
                                for topic, qlist in data.items():
                                    if isinstance(qlist, list):
                                        questions.extend(qlist)
                    except Exception as e:
                        st.warning(f"⚠️ Could not load {file_name}: {e}")
                random.shuffle(questions)

            # 🟢 Default — single file only
            else:
                st.sidebar.success(f"✅ Loaded questions from **{selected_file}** in **{selected_subject}**.")
                file_path = os.path.join(subject_path, selected_file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        for topic, qlist in data.items():
                            if isinstance(qlist, list):
                                questions.extend(qlist)
                    elif isinstance(data, list):
                        questions = data
                except Exception as e:
                    st.sidebar.error(f"Failed to load {selected_file}: {e}")

            # ✅ Only reset session state when new mode is chosen
            if (
                    st.session_state.get("current_file") != selected_file
                    or st.session_state.get("load_all_mode") != load_all_in_subject
                    or st.session_state.get("load_global_mode") != load_all_subjects
            ):
                st.session_state["current_file"] = selected_file
                st.session_state["load_all_mode"] = load_all_in_subject
                st.session_state["load_global_mode"] = load_all_subjects
                st.session_state.questions_loaded = questions
                st.session_state.q_index = 0
                st.session_state.score = 0
                st.session_state.answered = [False] * len(questions)
                st.session_state.feedback = [""] * len(questions)
                st.session_state.choices = [None] * len(questions)
            else:
                if "questions_loaded" not in st.session_state:
                    st.session_state.questions_loaded = questions

    # -----------------------------
    # SIDEBAR: LEADERBOARD + Controls + Folders
    # -----------------------------
    # Build leaderboard data for ALL users

    all_users = list(users_col.find())
    leaderboard_data = []

    for user in all_users:
        uid = user["user_id"]
        # Get the user's latest score from scores collection
        score_doc = scores_col.find_one({"user_id": uid}, sort=[("timestamp", -1)])
        score = score_doc["score"] if score_doc else 0
        leaderboard_data.append((uid, score))

    # Sort descending
    leaderboard_data.sort(key=lambda x: x[1], reverse=True)


    def position_suffix(i):
        return f"{i + 1}{'st' if i == 0 else 'nd' if i == 1 else 'rd' if i == 2 else 'th'}"


    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🥇 Leaderboard")
    with st.sidebar.container():
        st.markdown("<div style='max-height:300px; overflow-y:auto; padding-right:5px;'>", unsafe_allow_html=True)
        for i, (uid, score) in enumerate(leaderboard_data):
            user_doc = users_col.find_one({"user_id": uid})
            online_dot = "🟢" if is_user_online(user_doc) else "🔴"
            pos = position_suffix(i)
            st.markdown(f"**{pos}: {uid} — {score} {online_dot}**", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)


    st.sidebar.markdown("---")



    # -----------------------------
    # CHAT COLLECTION
    # -----------------------------
    chat_col = db["chat_messages"]


    def send_message(user_id, msg):
        """Insert message and keep only last 4 globally."""
        if msg.strip():
            chat_col.insert_one({
                "user_id": user_id,
                "message": msg.strip(),
                "timestamp": datetime.now()
            })

            users_col.update_one({"user_id": user_name}, {"$set": {"last_active": datetime.now()}})

            # Keep only last 4 messages globally
            count = chat_col.count_documents({})
            if count > 4:
                # Delete oldest messages beyond 4
                oldest = chat_col.find().sort("timestamp", 1).limit(count - 4)
                oldest_ids = [m["_id"] for m in oldest]
                chat_col.delete_many({"_id": {"$in": oldest_ids}})


    def get_messages(limit=4):
        """Return last 4 messages sorted oldest → newest."""
        messages = chat_col.find().sort("timestamp", 1).limit(limit)
        return [{"user_id": m["user_id"], "message": m["message"], "timestamp": m["timestamp"]} for m in messages]


    # -----------------------------
    # LOAD QUESTIONS
    # -----------------------------
    st.markdown(f"### 👤 Logged in as: {user_name}<br>", unsafe_allow_html=True)

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

    col1, col2 = st.columns(2)
    with col1:
        if st.button("⬅️ Previous Question"):
            st.session_state.nav_action = "prev"
    with col2:
        if st.button("➡️ Next Question"):
            st.session_state.nav_action = "next"

    if st.session_state.nav_action == "prev" and st.session_state.q_index > 0:
        st.session_state.q_index -= 1
    elif st.session_state.nav_action == "next" and st.session_state.q_index < len(questions) - 1:
        st.session_state.q_index += 1
        update_last_active(user_name)
        refresh_chat()

    st.session_state.nav_action = None

    # -----------------------------
    # LAYOUT: QUIZ + CHAT SIDE BY SIDE
    # -----------------------------
    col_main, col_chat = st.columns([3, 1])

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

                        # ✅ Auto-save score and update last_active
                        update_score(user_name, st.session_state.score, total_questions)
                        update_last_active(user_name)
                        refresh_chat()

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

    import urllib.parse

    # -----------------------------
    # CHAT SECTION (Form-based)
    # -----------------------------
    with col_chat:
        st.markdown("### 💬 Chat")

        # Initialize once only
        if "chat_messages" not in st.session_state:
            st.session_state.chat_messages = get_messages()

        # Refresh only if new messages were sent
        new_messages = get_messages()
        if len(new_messages) != len(st.session_state.chat_messages):
            st.session_state.chat_messages = new_messages

        # Display chat messages (scrollable)
        chat_container = st.container()
        with chat_container:
            st.markdown("<div style='max-height:400px; overflow-y:auto; padding-right:5px;'>",
                        unsafe_allow_html=True)
            for msg in st.session_state.chat_messages:
                username = msg["user_id"]
                message = msg["message"]
                timestamp = msg["timestamp"].strftime("%H:%M")
                if username == user_name:
                    st.markdown(
                        f"<div style='background-color:#4CAF50;color:white;padding:8px 12px;"
                        f"border-radius:12px;margin-bottom:6px;max-width:90%;margin-left:auto;'>"
                        f"<b>{username}</b> 🕓 {timestamp}<br>{message}</div>",
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(
                        f"<div style='background-color:#e0e0e0;color:black;padding:8px 12px;"
                        f"border-radius:12px;margin-bottom:6px;max-width:90%;margin-right:auto;'>"
                        f"<b>{username}</b> 🕓 {timestamp}<br>{message}</div>",
                        unsafe_allow_html=True
                    )
            st.markdown("</div>", unsafe_allow_html=True)

        # Chat input form
        with st.form(key="chat_form", clear_on_submit=True):
            chat_input = st.text_input("Type a message...", key="chat_input")
            submitted = st.form_submit_button("Send")

            if submitted and chat_input.strip():
                send_message(user_name, chat_input.strip())

                # ✅ Update last_active whenever user sends a chat message
                update_last_active(user_name)

                st.session_state.chat_messages = get_messages()
                st.rerun()  # clean rerun, no duplicates
