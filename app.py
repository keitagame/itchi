# -*- coding: utf-8 -*-
"""
一致ゲーム (Word Match Game) サーバー
------------------------------------
ルール:
 1. 任意の識別子(部屋ID)で部屋を作り、参加者が集まったら誰でも「ゲーム開始」を押せる
 2. 開始後、参加者がお題を考えて送信。最初に届いたお題を採用する
 3. 参加者全員が文字列を送信するか、2分(120秒)経過したら次に進む
 4. 他の誰かと文字列が一致していた参加者全員に1ポイント
 5. 次のターンへ(2に戻る。お題は再び最初に届いたものを採用)
 * 途中参加あり
 * ニックネームはいつでも変更可能
"""

import time
import threading
import uuid
from collections import defaultdict

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config["SECRET_KEY"] = "match-game-secret-" + uuid.uuid4().hex
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

ROUND_TIME_LIMIT = 120  # 秒 (2分)

# ------------------------------------------------------------------
# ゲーム状態管理
# ------------------------------------------------------------------
# rooms[room_id] = {
#   "players": { sid: {"nickname": str, "score": int, "connected": bool} },
#   "state": "lobby" | "collecting_topic" | "collecting_answers" | "round_result",
#   "topic": str | None,
#   "topic_owner": str | None,          # お題を最初に出した人のnickname
#   "answers": { sid: str },
#   "round_no": int,
#   "timer_end": float | None,          # そのラウンドの締切unixtime
#   "timer_token": int,                 # タイマー無効化用トークン
#   "history": [ {round, topic, answers:{nickname:word}, matched: [nickname,...]} ]
# }
rooms = defaultdict(lambda: {
    "players": {},
    "state": "lobby",
    "topic": None,
    "topic_owner": None,
    "answers": {},
    "round_no": 0,
    "timer_end": None,
    "timer_token": 0,
    "history": [],
})

rooms_lock = threading.Lock()


def public_room_state(room_id):
    """クライアントに送るための部屋の状態(パスワード等の秘匿情報なし)"""
    r = rooms[room_id]
    players = [
        {
            "sid": sid,
            "nickname": p["nickname"],
            "score": p["score"],
            "connected": p["connected"],
            "answered": sid in r["answers"] if r["state"] == "collecting_answers" else False,
        }
        for sid, p in r["players"].items()
    ]
    # ニックネーム順ではなく参加順を維持したいので dict の順序をそのまま使う
    remaining = None
    if r["state"] == "collecting_answers" and r["timer_end"]:
        remaining = max(0, int(r["timer_end"] - time.time()))

    return {
        "room_id": room_id,
        "state": r["state"],
        "players": players,
        "topic": r["topic"] if r["state"] in ("collecting_answers", "round_result") else None,
        "round_no": r["round_no"],
        "remaining_seconds": remaining,
        "last_result": r["history"][-1] if (r["state"] == "round_result" and r["history"]) else None,
    }


def broadcast_state(room_id):
    socketio.emit("state_update", public_room_state(room_id), room=room_id)


def connected_count(room_id):
    return sum(1 for p in rooms[room_id]["players"].values() if p["connected"])


def all_connected_answered(room_id):
    r = rooms[room_id]
    connected_sids = [sid for sid, p in r["players"].items() if p["connected"]]
    if not connected_sids:
        return False
    return all(sid in r["answers"] for sid in connected_sids)


# ------------------------------------------------------------------
# ラウンド進行ロジック
# ------------------------------------------------------------------
def start_round(room_id):
    """新しいラウンドを開始(お題募集フェーズへ)"""
    r = rooms[room_id]
    r["state"] = "collecting_topic"
    r["topic"] = None
    r["topic_owner"] = None
    r["answers"] = {}
    r["round_no"] += 1
    r["timer_end"] = None
    r["timer_token"] += 1
    broadcast_state(room_id)


def begin_answer_phase(room_id):
    """お題が決まったので回答収集フェーズへ。2分タイマーを開始する"""
    r = rooms[room_id]
    r["state"] = "collecting_answers"
    r["answers"] = {}
    r["timer_end"] = time.time() + ROUND_TIME_LIMIT
    r["timer_token"] += 1
    my_token = r["timer_token"]
    broadcast_state(room_id)

    def timeout_watcher(token):
        socketio.sleep(ROUND_TIME_LIMIT + 0.2)
        with rooms_lock:
            rr = rooms[room_id]
            if rr["timer_token"] == token and rr["state"] == "collecting_answers":
                finish_round(room_id, reason="timeout")

    socketio.start_background_task(timeout_watcher, my_token)


def finish_round(room_id, reason="all_answered"):
    """回答フェーズを締め切り、一致判定を行って結果を確定する"""
    r = rooms[room_id]
    if r["state"] != "collecting_answers":
        return
    r["timer_token"] += 1  # 進行中のタイマーを無効化

    # 文字列 -> nickname群 の対応を作る (前後空白除去、比較は完全一致)
    groups = defaultdict(list)
    answer_display = {}
    for sid, word in r["answers"].items():
        if sid not in r["players"]:
            continue
        nickname = r["players"][sid]["nickname"]
        normalized = word.strip()
        groups[normalized].append(sid)
        answer_display[nickname] = word.strip()

    matched_nicknames = []
    for normalized, sids in groups.items():
        if normalized == "":
            continue
        if len(sids) >= 2:
            for sid in sids:
                r["players"][sid]["score"] += 1
                matched_nicknames.append(r["players"][sid]["nickname"])

    r["history"].append({
        "round": r["round_no"],
        "topic": r["topic"],
        "answers": answer_display,
        "matched": matched_nicknames,
        "reason": reason,
    })
    r["state"] = "round_result"
    r["timer_end"] = None
    broadcast_state(room_id)

    # 少し結果を見せてから次のラウンド(お題募集)へ自動移行
    def advance():
        socketio.sleep(6)
        with rooms_lock:
            if rooms[room_id]["state"] == "round_result":
                start_round(room_id)

    socketio.start_background_task(advance)


# ------------------------------------------------------------------
# HTTP ルート
# ------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ------------------------------------------------------------------
# Socket.IO イベント
# ------------------------------------------------------------------
@socketio.on("join_room_event")
def handle_join(data):
    room_id = (data.get("room_id") or "").strip()
    nickname = (data.get("nickname") or "").strip() or f"ゲスト{request.sid[:4]}"

    if not room_id:
        emit("error_message", {"message": "部屋IDを入力してください。"})
        return

    with rooms_lock:
        join_room(room_id)
        r = rooms[room_id]
        # 途中参加: 既存の部屋にそのまま参加(スコアは0から)
        r["players"][request.sid] = {
            "nickname": nickname,
            "score": 0,
            "connected": True,
        }

    emit("joined", {"room_id": room_id, "nickname": nickname})
    socketio.emit(
        "system_message",
        {"message": f"{nickname} さんが参加しました。"},
        room=room_id,
    )
    broadcast_state(room_id)


@socketio.on("change_nickname")
def handle_change_nickname(data):
    room_id = data.get("room_id")
    new_nickname = (data.get("nickname") or "").strip()
    if not room_id or room_id not in rooms:
        return
    if not new_nickname:
        emit("error_message", {"message": "ニックネームを入力してください。"})
        return

    with rooms_lock:
        r = rooms[room_id]
        player = r["players"].get(request.sid)
        if not player:
            return
        old_nickname = player["nickname"]
        player["nickname"] = new_nickname

    socketio.emit(
        "system_message",
        {"message": f"{old_nickname} さんが「{new_nickname}」に改名しました。"},
        room=room_id,
    )
    broadcast_state(room_id)


@socketio.on("start_game")
def handle_start_game(data):
    room_id = data.get("room_id")
    if not room_id or room_id not in rooms:
        return
    with rooms_lock:
        r = rooms[room_id]
        if r["state"] != "lobby":
            return
        if connected_count(room_id) < 2:
            emit("error_message", {"message": "ゲーム開始には2人以上必要です。"})
            return
        start_round(room_id)


@socketio.on("submit_topic")
def handle_submit_topic(data):
    room_id = data.get("room_id")
    topic = (data.get("topic") or "").strip()
    if not room_id or room_id not in rooms or not topic:
        return

    with rooms_lock:
        r = rooms[room_id]
        if r["state"] != "collecting_topic":
            return  # 既に誰かのお題が採用済み、または不正なタイミング
        player = r["players"].get(request.sid)
        if not player:
            return
        r["topic"] = topic
        r["topic_owner"] = player["nickname"]
        begin_answer_phase(room_id)

    socketio.emit(
        "system_message",
        {"message": f"お題「{topic}」({player['nickname']} さん提案)で開始します！"},
        room=room_id,
    )


@socketio.on("submit_answer")
def handle_submit_answer(data):
    room_id = data.get("room_id")
    answer = data.get("answer", "")
    if not room_id or room_id not in rooms:
        return
    if not isinstance(answer, str) or answer.strip() == "":
        emit("error_message", {"message": "文字列を入力してください。"})
        return

    should_finish = False
    with rooms_lock:
        r = rooms[room_id]
        if r["state"] != "collecting_answers":
            return
        if request.sid not in r["players"]:
            return
        r["answers"][request.sid] = answer
        if all_connected_answered(room_id):
            should_finish = True

    broadcast_state(room_id)
    if should_finish:
        finish_round(room_id, reason="all_answered")


@socketio.on("disconnect")
def handle_disconnect():
    with rooms_lock:
        for room_id, r in list(rooms.items()):
            if request.sid in r["players"]:
                r["players"][request.sid]["connected"] = False
                nickname = r["players"][request.sid]["nickname"]
                should_finish = False
                if r["state"] == "collecting_answers" and all_connected_answered(room_id):
                    should_finish = True
                socketio.emit(
                    "system_message",
                    {"message": f"{nickname} さんが退出しました。"},
                    room=room_id,
                )
                broadcast_state(room_id)
                if should_finish:
                    finish_round(room_id, reason="all_answered")


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=8000, debug=True, allow_unsafe_werkzeug=True)
