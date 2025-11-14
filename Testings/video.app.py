from flask import Flask, render_template_string, Response
import cv2

app = Flask(__name__)

# Function to capture video from the default camera (index 0)
def generate_frames():
    camera = cv2.VideoCapture(0)  # Use 0 for the default webcam
    
    if not camera.isOpened():
        print("Error: Could not open camera.")
        return

    while True:
        # Read a frame from the camera
        success, frame = camera.read()
        if not success:
            break
        else:
            # Encode the frame as JPEG
            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            
            # Convert the buffer to bytes
            frame_bytes = buffer.tobytes()

            # Yield the frame in the multipart format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    
    camera.release()

@app.route('/')
def index():
    # HTML to display the video stream
    return render_template_string("""
        <html>
            <head><title>Live Video Stream</title></head>
            <body>
                <h1>Live Webcam Feed (from Server)</h1>
                <img src="{{ url_for('video_feed') }}">
            </body>
        </html>
    """)

@app.route('/video_feed')
def video_feed():
    # Return the streaming response
    return Response(generate_frames(), 
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(debug=True, port=5000)