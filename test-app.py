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
BASE_FOLDER = "."
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


    # -----------------------------
    # SIDEBAR: LEADERBOARD + Controls + Folders
    # -----------------------------
    load_scores_cache()
    leaderboard_data = []
    df = pd.DataFrame(st.session_state.get("scores_cache", []))
    if not df.empty and "score" in df.columns:
        sheet_leaderboard = df.groupby("user_id")["score"].max().reset_index()
        sheet_leaderboard = sheet_leaderboard.sort_values(by="score", ascending=False)
        for _, row in sheet_leaderboard.iterrows():
            leaderboard_data.append((row["user_id"], row["score"]))
    leaderboard_data = [x for x in leaderboard_data if x[0] != user_name]
    leaderboard_data.append((user_name, st.session_state.get("score", 0)))
    leaderboard_data.sort(key=lambda x: x[1], reverse=True)

    def position_suffix(i):
        return f"{i + 1}{'st' if i == 0 else 'nd' if i == 1 else 'rd' if i == 2 else 'th'}"


    st.sidebar.markdown(f"### 👤 Logged in as: {user_name}")
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
    st.sidebar.markdown("### 📂 Subjects & Topics")


    def display_folder_structure(base_folder):
        subjects = [f for f in sorted(os.listdir(base_folder)) if os.path.isdir(os.path.join(base_folder, f))]
        if not subjects:
            st.sidebar.info("No question folders found yet.")
            return

        last_subject = subjects[-1]
        for subject in subjects:
            subject_path = os.path.join(base_folder, subject)
            topic_files = [f for f in sorted(os.listdir(subject_path)) if
                           any(f.endswith(ext) for ext in QUESTIONS_FILE_TYPES)]
            if not topic_files:
                continue

            # Subject name
            st.sidebar.markdown(
                f"<div style='color:#1E90FF; font-weight:600; font-size:16px;'>📘 {subject}</div>",
                unsafe_allow_html=True
            )

            # Loop through each topic file
            for topic in topic_files:
                topic_name = os.path.splitext(topic)[0].replace("_", " ").title()
                topic_path = os.path.join(subject_path, topic)

                # Count number of questions inside each topic file
                try:
                    with open(topic_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        question_count = sum(len(qlist) for qlist in data.values())
                except Exception:
                    question_count = 0  # fallback if file cannot be read

                # Display topic name + question count
                st.sidebar.markdown(
                    f"<div style='padding-left:20px; font-size:14px; color:#555;'>• {topic_name} "
                    f"<span style='color:#1E90FF;'>({question_count})</span></div>",
                    unsafe_allow_html=True
                )

            if subject != last_subject:
                st.sidebar.markdown("<hr style='margin:6px 0;'>", unsafe_allow_html=True)


    display_folder_structure(BASE_FOLDER)
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
    def load_questions(path):
        questions = []
        files_to_load = [path] if os.path.isfile(path) else [
            os.path.join(path, f) for f in os.listdir(path) if any(f.endswith(ext) for ext in QUESTIONS_FILE_TYPES)
        ]
        for file_path in files_to_load:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for topic, qlist in data.items():
                        questions.extend(qlist)
            except Exception as e:
                st.warning(f"Could not load {file_path}: {e}")
        return questions

    def load_all_questions():
        all_questions = []
        for folder_name in sorted(os.listdir(BASE_FOLDER)):
            folder_path = os.path.join(BASE_FOLDER, folder_name)
            if os.path.isdir(folder_path):
                for file_name in sorted(os.listdir(folder_path)):
                    if any(file_name.endswith(ext) for ext in QUESTIONS_FILE_TYPES):
                        file_path = os.path.join(folder_path, file_name)
                        all_questions.extend(load_questions(file_path))
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
