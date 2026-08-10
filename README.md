

# 🎬 PyMontage - Automatic Video Slideshow Creator

![Version](https://img.shields.io/badge/version-1.0.1-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![Flask](https://img.shields.io/badge/flask-3.0.0-green.svg)
![License](https://img.shields.io/badge/license-MIT-orange.svg)

**PyMontage** is a powerful web-based application that automatically creates professional video slideshows from your photos and music. Upload your images, select a soundtrack, and let PyMontage do the rest!

**Version 1.0.1 Release** - Enhanced with Google Fonts integration, automatic server cleanup, and improved font management system.

## ✨ Features

- 🖼️ **Smart Image Processing**: Automatically organizes and displays photos with intelligent layouts (2x2 grids, 1x3 grids, collages, single images)
- 🎵 **Audio Synchronization**: Perfectly syncs slideshow duration with your background music
- 🎶 **Multiple Soundtrack Support**: Add multiple audio files with smooth crossfading between tracks
- 🎨 **Flexible Layout Modes**: Enable/disable specific layout types (Grid 2x2, Grid 1x3, Collage, Single)
- 📊 **Real-time Progress Bar**: Track video creation progress with detailed status updates
- ⚙️ **Full Customization**: Control resolution, timing, transitions, fonts, and quality settings
- 🎬 **Professional Output**: High-quality video output with smooth transitions and title cards
- 🔤 **Custom Fonts**: Choose from built-in Windows fonts or download from Google Fonts
- 🔎 **Font Search**: Search and instantly download any font from Google Fonts library
- 🧹 **Auto Cleanup**: Automatic cleanup of temporary files and cache on shutdown
- 🌐 **Web Interface**: Easy-to-use browser-based interface with drag-and-drop support
- 📱 **Format Support**: Supports JPG, PNG, HEIC, GIF, BMP, TIFF, WebP, and more
- 🎥 **Hardware Acceleration**: Automatic GPU detection for faster rendering (NVIDIA NVENC)
- 🗂️ **Smart File Management**: Add images incrementally, preview selections, and remove specific files

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- FFmpeg installed on your system ([Download FFmpeg](https://ffmpeg.org/download.html))

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Ariel-Gal/PyMontage.git
   cd PyMontage
   ```

2. **Create and activate virtual environment:**
   
   **Windows:**
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```
   
   **macOS/Linux:**
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Prepare media paths (pick one):**
   - **Default (repo-relative):** place photos in `input/photos/`, background track as `input/audio.mp3`, and ensure `output/` exists for the rendered video.
   - **Custom paths:** set env vars before running:
     ```bash
     set PYMONTAGE_IMAGE_FOLDER="C:\path\to\photos"   # Windows
     set PYMONTAGE_AUDIO_FILE="C:\path\to\music.mp3"
     set PYMONTAGE_OUTPUT_FILE="C:\path\to\slideshow.mp4"
     ```
     (macOS/Linux: use `export VAR=value`)

5. **Run the application:**
   ```bash
   python app.py
   ```

6. **Open your browser:**
   Navigate to `http://127.0.0.1:5000`

## 📖 Usage

1. **Upload Images**: 
   - Click "Select Images" and choose multiple photos
   - You can add more images later without removing previous selections
   - Preview thumbnails show all selected images
   - Remove specific images by clicking the × button
2. **Select Music**: 
   - Upload one or more MP3/WAV files
   - Multiple tracks will be smoothly crossfaded with adjustable overlap duration
   - Total duration is calculated including crossfade transitions
3. **Add Titles** (optional): Set custom intro and outro text
4. **Advanced Settings** (optional): Click "Show Advanced Settings" to customize:
   - **Video Resolution**: Choose from presets (720p to 4K) or custom dimensions
   - **Timing Settings**: Control transition duration, intro/outro card duration, and pauses
   - **Layout Modes**: Enable/disable specific layouts (Grid 2×2, Grid 1×3, Collage, Single)
   - **Display Weights**: Adjust relative duration for each layout type
   - **Video Quality**: Set FPS, bitrate, and compression quality
   - **Text Styling**: Choose font family and adjust font sizes
   - **Image Processing**: Set maximum image width for memory optimization
5. **Create Video**: 
   - Click "Create & Download Video"
   - Watch the progress bar for status updates
   - Processing may take several minutes
6. **Download**: Your video will automatically download when ready

## ⚙️ Configuration Options

### Paths & environment variables
- Default (repo-relative): images in `input/photos/`, audio in `input/audio.mp3`, output to `output/slideshow.mp4`.
- Override for CI/servers by setting `PYMONTAGE_IMAGE_FOLDER`, `PYMONTAGE_AUDIO_FILE`, `PYMONTAGE_OUTPUT_FILE`.

### Basic Settings
- **Intro Text**: Opening title displayed at the beginning
- **Outro Text**: Closing title displayed at the end

### Advanced Settings
- **Resolution**: Synchronized presets (720p, 1080p, 2K, 4K) or custom dimensions
- **Timing Settings**:
  - Transition Duration: Crossfade time between slides (0-3 seconds)
  - Intro Card Duration: How long the opening title displays
  - Outro Card Duration: How long the closing title displays
  - Opening Pause: Black screen before intro (0-10 seconds)
  - Closing Pause: Black screen after outro (0-10 seconds)
- **Audio Settings**:
  - Audio Crossfade Duration: Smooth transition overlap between multiple soundtracks (0-10 seconds)
- **Layout Modes**: Select which layout types to enable:
  - Grid 2×2: 4 horizontal images per slide
  - Grid 1×3: 3 vertical images per slide
  - Collage 1×2: 2 images per slide
  - Single Image: 1 image per slide
- **Display Weights**: Relative duration for different slide types
  - Grid Weight: Duration multiplier for 2×2 grid slides
  - Triple Weight: Duration multiplier for 1×3 grid slides
  - Collage Weight: Duration multiplier for 2-image slides
  - Single Weight: Duration multiplier for single image slides
- **Video Quality**:
  - FPS: 24 (cinematic), 30 (standard), or 60 (smooth)
  - Bitrate: 2000k (low) to 15000k (ultra)
  - CRF Quality: 18 (best quality) to 32 (smaller file)
- **Text Styling**:
  - Font Family: Choose from built-in Windows fonts or search and download from Google Fonts
  - Title Font Size: Size for intro/outro text (30-200)
  - Date Font Size: Size for date overlays (20-150)
  - Font Search: Live search to find and download fonts from Google Fonts library
- **Image Processing**:
  - Max Image Width: Downscale images to save memory (1920-4800 pixels)

## 🛠️ Technical Details

### Architecture
- **Backend**: Flask (Python web framework) with signal handlers for graceful shutdown
- **Video Processing**: MoviePy, OpenCV, FFmpeg
- **Audio Analysis**: librosa
- **Frontend**: HTML5, Bootstrap 5, vanilla JavaScript with async font management
- **Font Management**: Google Fonts API integration with local caching and automatic downloads
- **Cleanup System**: Automatic cleanup of temporary files, cache, and bytecode on exit

### File Structure
```
PyMontage/
├── app.py                  # Flask web server
├── video_engine.py         # Core video creation logic
├── timeline_renderer.py    # Timeline rendering & export engine
├── templates/
│   └── index.html          # Web interface
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── input/
│   ├── photos/             # Default images location
│   └── audio.mp3           # Default soundtrack
└── output/                 # Rendered videos (default target)
```

### Supported Formats
- **Images**: JPG, JPEG, PNG, GIF, BMP, TIF, TIFF, WebP, HEIC, HEIF
- **Audio**: MP3, WAV, M4A, FLAC, OGG
- **Output**: MP4 (H.264 video, AAC audio)

## 🔧 Troubleshooting

### FFmpeg Not Found
Ensure FFmpeg is installed and available in your system PATH:
```bash
ffmpeg -version
```

### HEIC Images Not Working
Install pillow-heif for HEIC support (included in requirements.txt):
```bash
pip install pillow-heif
```

### GPU Acceleration Not Working
- Ensure NVIDIA drivers are up to date
- Check CUDA installation
- The application will automatically fall back to CPU encoding if GPU is unavailable

### Memory Issues with Large Images
The application automatically downscales images to optimize memory usage. Adjust the "Max Image Width" setting in Advanced Settings (default: 3840px).

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 👨‍💻 Author

**Ariel Gal**

- GitHub: [@Ariel-Gal](https://github.com/Ariel-Gal)

## 🙏 Acknowledgments

- [MoviePy](https://zulko.github.io/moviepy/) - Video editing library
- [Flask](https://flask.palletsprojects.com/) - Web framework
- [Bootstrap](https://getbootstrap.com/) - UI framework
- [FFmpeg](https://ffmpeg.org/) - Multimedia framework

## 📧 Support

If you encounter any issues or have questions, please [open an issue](https://github.com/Ariel-Gal/PyMontage/issues) on GitHub.

---

Made with ❤️ by Ariel Gal
