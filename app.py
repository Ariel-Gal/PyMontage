import os
import shutil
import uuid
import atexit
import signal
from flask import Flask, render_template, request, send_file, after_this_request
from video_engine import generate_video_from_web  # Import from video_engine.py

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'temp_uploads'
app.config['OUTPUT_FOLDER'] = 'temp_outputs'

# Create temporary folders if they don't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

def cleanup_temp_folders():
    """Clean up all temporary folders when server shuts down"""
    print("\n🧹 Cleaning up temporary folders...")
    try:
        if os.path.exists(app.config['UPLOAD_FOLDER']):
            shutil.rmtree(app.config['UPLOAD_FOLDER'])
            print(f"  ✓ Removed {app.config['UPLOAD_FOLDER']}")
        if os.path.exists(app.config['OUTPUT_FOLDER']):
            shutil.rmtree(app.config['OUTPUT_FOLDER'])
            print(f"  ✓ Removed {app.config['OUTPUT_FOLDER']}")
        print("✓ Cleanup complete!")
    except Exception as e:
        print(f"⚠ Warning: Could not clean up temp folders: {e}")

def signal_handler(signum, frame):
    """Handle termination signals (Ctrl+C, etc.)"""
    print(f"\n\n🛑 Received signal {signum}, shutting down server...")
    cleanup_temp_folders()
    exit(0)

# Register cleanup handlers
atexit.register(cleanup_temp_folders)
signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # Termination signal

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/create', methods=['POST'])
def create_video():
    # Create unique session ID to avoid conflicts
    session_id = str(uuid.uuid4())
    session_upload_path = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
    session_images_path = os.path.join(session_upload_path, 'images')
    os.makedirs(session_images_path, exist_ok=True)
    
    try:
        # 1. Save audio file(s) - support multiple
        if 'audio' not in request.files:
            return "No audio file uploaded", 400
        audio_files = request.files.getlist('audio')
        audio_paths = []
        for idx, audio_file in enumerate(audio_files):
            if audio_file.filename:
                audio_filename = f'music_{idx}.mp3'
                audio_path = os.path.join(session_upload_path, audio_filename)
                audio_file.save(audio_path)
                audio_paths.append(audio_path)
        
        # Check if we have valid audio files
        if not audio_paths:
            return "No valid audio file", 400
        
        # 2. Save images
        if 'images' not in request.files:
            return "No images uploaded", 400
        files = request.files.getlist('images')
        for file in files:
            if file.filename:
                file.save(os.path.join(session_images_path, file.filename))
        
        # 3. Get text inputs
        intro_text = request.form.get('intro_text', 'My Slideshow')
        outro_text = request.form.get('outro_text', 'Thanks for watching')
        
        # 4. Get configuration parameters
        config = {
            'target_width': int(request.form.get('target_width', 1920)),
            'target_height': int(request.form.get('target_height', 1080)),
            'transition_duration': float(request.form.get('transition_duration', 0.5)),
            'intro_card_duration': float(request.form.get('intro_card_duration', 3.0)),
            'outro_card_duration': float(request.form.get('outro_card_duration', 3.0)),
            'opening_pause': float(request.form.get('opening_pause', 2.0)),
            'closing_pause': float(request.form.get('closing_pause', 2.0)),
            
            # Layout modes - check which are enabled
            'enable_grid_2x2': request.form.get('enable_grid_2x2') == 'true',
            'enable_grid_1x3': request.form.get('enable_grid_1x3') == 'true',
            'enable_collage': request.form.get('enable_collage') == 'true',
            'enable_single': request.form.get('enable_single') == 'true',
            
            'grid_weight': float(request.form.get('grid_weight', 2.0)),
            'collage_weight': float(request.form.get('collage_weight', 1.5)),
            'triple_weight': float(request.form.get('triple_weight', 1.75)),
            'single_weight': float(request.form.get('single_weight', 1.0)),
            'video_fps': int(request.form.get('video_fps', 24)),
            'video_bitrate': request.form.get('video_bitrate', '4000k'),
            'video_quality': int(request.form.get('video_quality', 23)),
            'title_font_size': int(request.form.get('title_font_size', 100)),
            'date_font_size': int(request.form.get('date_font_size', 70)),
            'max_image_width': int(request.form.get('max_image_width', 2400)),
            'font_family': request.form.get('font_family', 'trebucbd.ttf'),
            'audio_crossfade': float(request.form.get('audio_crossfade', 3.0)),
        }
        
        # 5. Set output path
        output_filename = f"video_{session_id}.mp4"
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
        
        # 6. Run the video engine with all audio paths
        success, message = generate_video_from_web(
            image_folder=session_images_path,
            audio_paths=audio_paths,
            output_path=output_path,
            intro_text=intro_text,
            outro_text=outro_text,
            config=config
        )
        
        if success:
            # Clean up source files after completion (optional)
            shutil.rmtree(session_upload_path)
            
            # Send file to user and delete it after sending
            @after_this_request
            def remove_file(response):
                try:
                    if os.path.exists(output_path):
                        os.remove(output_path)
                except Exception as e:
                    print(f"Error removing file: {e}")
                return response
                
            return send_file(output_path, as_attachment=True, download_name='my_slideshow.mp4')
        else:
            return f"Error creating video: {message}", 500

    except Exception as e:
        return f"Server Error: {e}", 500

if __name__ == '__main__':
    print("="*70)
    print("  🎬 PyMontage Server Starting...")
    print("  📁 Temporary folders will be cleaned on shutdown")
    print("  🌐 Server: http://127.0.0.1:5000")
    print("  ⚠  Press Ctrl+C to stop server and cleanup temp files")
    print("="*70 + "\n")
    app.run(debug=False, port=5000)


