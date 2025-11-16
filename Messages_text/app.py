from flask import Flask, render_template, request, redirect, url_for
import os

app = Flask(__name__)

FRIENDS_FILE = "friends.txt"
MSG_FOLDER = "messages"

# Create message folder if not exists
if not os.path.exists(MSG_FOLDER):
    os.makedirs(MSG_FOLDER)


def read_friends():
    with open(FRIENDS_FILE, "r") as f:
        return [line.strip() for line in f.readlines()]


def read_messages(friend):
    path = os.path.join(MSG_FOLDER, f"{friend}.txt")
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return f.readlines()


def write_message(friend, msg):
    path = os.path.join(MSG_FOLDER, f"{friend}.txt")
    with open(path, "a") as f:
        f.write(msg + "\n")


@app.route("/")
def index():
    friends = read_friends()
    return render_template("index.html", friends=friends)


@app.route("/chat/<friend>", methods=["GET", "POST"])
def chat(friend):
    if request.method == "POST":
        msg = request.form.get("message")
        if msg.strip() != "":
            write_message(friend, msg)
        return redirect(url_for("chat", friend=friend))

    messages = read_messages(friend)
    friends = read_friends()
    return render_template("chat.html", friend=friend, messages=messages, friends=friends)


if __name__ == "__main__":
    app.run(debug=True)
