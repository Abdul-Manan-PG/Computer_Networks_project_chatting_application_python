from flask import Flask, render_template, Response
import threading
import time

app = Flask(__name__)

latest_frame = b""

def generate_stream():
    global latest_frame
    while True:
        if latest_frame:
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + latest_frame + b"\r\n")
        time.sleep(0.03)

@app.route("/")
def index():
    return render_template("video.html")

@app.route("/video_feed")
def video_feed():
    return Response(generate_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")

# called by client
def update_frame(frame):
    global latest_frame
    latest_frame = frame




if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5500, debug=False, threaded=True)
