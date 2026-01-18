"""
Simple Video Slideshow Creator
Creates a basic video slideshow from images without effects.
Just loads images chronologically and displays them full (no cropping).
"""

import hashlib
import os
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
import tempfile
import json
import random
import requests
import zipfile
import io

import cv2
from PIL import Image, ExifTags
from moviepy.editor import (
    AudioFileClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    ColorClip,
    concatenate_videoclips,
    concatenate_audioclips,
    CompositeAudioClip,
)
from moviepy.audio.AudioClip import AudioClip
from tqdm import tqdm
import numpy as np
import librosa
from typing import Optional

# Register HEIF/HEIC support
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    print("✅ HEIC/HEIF support enabled")
except ImportError:
    print("⚠️ pillow-heif not installed, HEIC/HEIF files won't be supported")
except Exception as e:
    print(f"⚠️ Could not enable HEIC/HEIF support: {e}")

def install_google_font(font_name):
    """
    Downloads a font from Google Fonts, extracts it, and saves to assets/fonts directory.
    Uses multiple fallback methods to download the font.
    
    Args:
        font_name: Name of the font (e.g., "Heebo", "Roboto")
    
    Returns:
        Path to the installed font file, or None if failed
    
    Example:
        font_path = install_google_font("Heebo")
        if font_path:
            TITLE_FONT_PATH = font_path
    """
    # Save directory
    save_dir = os.path.join("assets", "fonts")
    os.makedirs(save_dir, exist_ok=True)
    
    # Check if font already exists (avoid unnecessary downloads)
    font_path = os.path.join(save_dir, f"{font_name}-Regular.ttf")
    if os.path.exists(font_path):
        print(f"✓ Font already installed: {font_path}")
        return font_path

    print(f"📥 Downloading font: {font_name} from Google Fonts...")
    
    # Method 1: Try Google Fonts API (requires parsing but works reliably)
    try:
        # Get font metadata from Google Fonts API
        api_url = f"https://fonts.googleapis.com/css?family={font_name.replace(' ', '+')}"
        response = requests.get(api_url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        
        if response.status_code == 200:
            # Parse CSS to find TTF URL
            import re
            # Look for url() in the CSS
            ttf_urls = re.findall(r'url\((https://[^)]+\.ttf)\)', response.text)
            
            if ttf_urls:
                # Download the first TTF file
                ttf_response = requests.get(ttf_urls[0], timeout=30)
                if ttf_response.status_code == 200:
                    font_path = os.path.join(save_dir, f"{font_name}-Regular.ttf")
                    with open(font_path, 'wb') as f:
                        f.write(ttf_response.content)
                    print(f"✅ Font installed: {font_path}")
                    return font_path
        
        print(f"⚠️ Could not download {font_name} automatically")
        print(f"💡 You can manually download it from https://fonts.google.com/ and place it in {save_dir}")
        return None
                    
    except Exception as e:
        print(f"❌ Failed to download font: {e}")
        print(f"💡 You can manually download {font_name} from https://fonts.google.com/ and place it in {save_dir}")
        return None


def resolve_font_path(font_name: str) -> Optional[str]:
    """Resolve a font name or path, downloading from Google Fonts if missing."""
    if not font_name:
        return None

    # Absolute path
    if os.path.isabs(font_name) and os.path.exists(font_name):
        return font_name

    # Relative assets/fonts path
    assets_path = os.path.join("assets", "fonts", font_name)
    if os.path.exists(assets_path):
        return assets_path

    # System fonts directory fallback (platform-specific)
    if os.name == "nt":
        # Windows system fonts
        windows_font = os.path.join(r"C:\Windows\Fonts", font_name)
        if os.path.exists(windows_font):
            return windows_font
    else:
        # Common font directories on Unix-like systems (Linux, macOS)
        home = Path.home()
        font_dirs = [
            "/usr/share/fonts",
            "/usr/local/share/fonts",
            str(home / ".local" / "share" / "fonts"),
            "/System/Library/Fonts",
            "/Library/Fonts",
            str(home / "Library" / "Fonts"),
        ]
        for font_dir in font_dirs:
            candidate = os.path.join(font_dir, font_name)
            if os.path.exists(candidate):
                return candidate

    # Try downloading from Google Fonts (strip extension)
    base_name = os.path.splitext(font_name)[0]
    downloaded = install_google_font(base_name)
    if downloaded and os.path.exists(downloaded):
        return downloaded

    return None

def read_image_safe(path, max_width=None):
    """
    Helper function to read images with non-ASCII (Hebrew) characters in path.
    Replaces cv2.imread which fails on Unicode paths in Windows.
    
    OPTIMIZATION: Downscales images immediately during read to reduce memory usage
    and speed up face detection and rendering.
    
    Args:
        path: Image file path
        max_width: Maximum width in pixels (uses MAX_IMAGE_WIDTH from config if None)
    """
    if max_width is None:
        max_width = MAX_IMAGE_WIDTH
    
    try:
        # Check if file is HEIC/HEIF (cv2 doesn't support them)
        path_lower = str(path).lower()
        if path_lower.endswith(('.heic', '.heif', '.heics', '.heifs')):
            # Use PIL for HEIC/HEIF files
            img_pil = Image.open(path)
            
            # Convert to RGB if needed
            if img_pil.mode != 'RGB':
                img_pil = img_pil.convert('RGB')
            
            # OPTIMIZATION: Downscale immediately if image is too large
            if img_pil.width > max_width:
                scale_factor = max_width / img_pil.width
                new_width = max_width
                new_height = int(img_pil.height * scale_factor)
                img_pil = img_pil.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Convert PIL to OpenCV format
            img = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
            return img
        
        # For other formats, use cv2 (faster)
        # Open file directly via Python (handles Hebrew correctly)
        with open(path, "rb") as f:
            file_bytes = bytearray(f.read())
            numpy_array = np.asarray(file_bytes, dtype=np.uint8)
            # Decode the bytes to OpenCV image
            img = cv2.imdecode(numpy_array, cv2.IMREAD_COLOR)
            
            # OPTIMIZATION: Downscale immediately if image is too large
            # This reduces memory usage and speeds up face detection
            if img is not None and img.shape[1] > max_width:
                scale_factor = max_width / img.shape[1]
                new_width = max_width
                new_height = int(img.shape[0] * scale_factor)
                img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_AREA)
            
            return img
    except Exception as e:
        print(f"Error reading file {path}: {e}")
        return None


# ==================== CONFIGURATION ====================

# ===== PATHS =====
# Use repo-relative defaults with optional environment overrides for portability (works on CI/GitHub too)
PROJECT_ROOT = Path(__file__).resolve().parent
IMAGE_FOLDER_PATH = os.getenv("PYMONTAGE_IMAGE_FOLDER", str(PROJECT_ROOT / "input" / "photos"))
AUDIO_FILE_PATH = os.getenv("PYMONTAGE_AUDIO_FILE", str(PROJECT_ROOT / "input" / "audio.mp3"))
OUTPUT_FILE_PATH = os.getenv("PYMONTAGE_OUTPUT_FILE", str(PROJECT_ROOT / "output" / "slideshow.mp4"))

# ===== TEXT CONTENT =====
INTRO_TEXT = "Our Family Memories"
OUTRO_TEXT = "See you in happy times!"

# ===== VIDEO RESOLUTION =====
TARGET_WIDTH = 1920
TARGET_HEIGHT = 1080

# ===== TIMING SETTINGS =====
TRANSITION_DURATION = 0.5      # Crossfade duration in seconds
FIXED_INTRO_TIME = 7.5         # Reserved time for intro+pause at start (seconds)
INTRO_CARD_DURATION = 3.0      # Duration of intro title card (seconds)
OUTRO_CARD_DURATION = 3.0      # Duration of outro title card (seconds)
OPENING_PAUSE_DURATION = 2.0   # Black pause before intro (seconds)
CLOSING_PAUSE_DURATION = 2.0   # Black pause after outro (seconds)

# ===== LAYOUT MODE =====
# USE_GRID_2X2: True = 2x2 grids (4 images per slide), False = single images
USE_GRID_2X2 = True

# ===== DISPLAY TYPE WEIGHTS =====
# Different screen layouts get different durations (relative weights)
GRID_WEIGHT = 2.0        # 2x2 Grid (4 horizontal images) - gets most screen time
TRIPLE_WEIGHT = 1.75     # 1x3 Grid (3 vertical images) - gets more than collage
COLLAGE_WEIGHT = 1.5     # 1x2 Collage (2 images) - gets medium screen time
SINGLE_WEIGHT = 1.0      # 1x1 Single (1 image) - gets least screen time

# ===== RENDERING SETTINGS =====
VIDEO_FPS = 24                 # Frames per second for output video
VIDEO_BITRATE = '4000k'        # Video bitrate (higher = better quality, larger file)
VIDEO_CODEC_PREFERENCE = 'auto'  # 'auto', 'h264_nvenc' (NVIDIA GPU), 'libx264' (CPU)
VIDEO_QUALITY = 32             # CRF/CQ value (lower = better quality, 18-32 recommended)

# ===== IMAGE PROCESSING =====
MAX_IMAGE_WIDTH = 2400         # Maximum width for loaded images (pixels, reduces memory)

# ===== TEXT STYLING =====
TITLE_FONT_PATH = r"C:\Windows\Fonts\trebucbd.ttf"  # Font for titles
TITLE_FONT_SIZE = 100          # Font size for intro/outro titles
DATE_FONT_PATH = r"C:\Windows\Fonts\trebucbd.ttf"   # Font for date overlays
DATE_FONT_SIZE = 70            # Font size for date overlays

# ===== CACHE SETTINGS =====
USE_CACHE = False               # Enable caching to skip re-rendering if nothing changed

# NOTE: Image duration is calculated automatically!
# The script divides (audio_length - FIXED_INTRO_TIME) by total weighted slides
# This ensures all images fit perfectly to the audio length.

# Image file extensions
SUPPORTED_EXTENSIONS = (
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tif', '.tiff', '.webp', '.heic', '.heif'
)

# Video file extensions
SUPPORTED_VIDEO_EXTENSIONS = (
    '.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm', '.m4v'
)
# =======================================================


def get_best_video_codec():
    """Detect available GPU codecs - prefer h264_nvenc which uses less VRAM."""
    # Find ffmpeg first
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        # Try to find ffmpeg from imageio_ffmpeg
        try:
            import imageio_ffmpeg
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        except:
            pass
    
    if not ffmpeg_path:
        print("⚠ FFmpeg not found in PATH, using CPU (libx264)")
        return 'libx264'
    
    try:
        result = subprocess.run([ffmpeg_path, '-codecs'], capture_output=True, text=True, timeout=5)
        output = result.stdout.lower()
        
        # Check for NVIDIA codecs - h264_nvenc uses less VRAM than hevc
        if 'h264_nvenc' in output:
            print("✓ Found NVIDIA H.264 GPU codec (h264_nvenc) - lower VRAM usage")
            return 'h264_nvenc'
        if 'hevc_nvenc' in output:
            print("✓ Found NVIDIA HEVC GPU codec (hevc_nvenc)")
            return 'hevc_nvenc'
        
        print("⚠ No NVIDIA GPU codecs found, using CPU (libx264)")
        return 'libx264'
    except Exception as e:
        print(f"⚠ Could not check GPU codecs: {e}, using CPU (libx264)")
        return 'libx264'


def load_and_sort_images(folder_path):
    """Load image and video files from folder, sorted chronologically by EXIF/file date and grouped by date."""
    
    def md5_for_file(path):
        """Compute MD5 hash for duplicate detection."""
        h = hashlib.md5()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        return h.hexdigest()

    def parse_exif_datetime(path):
        """Extract date from EXIF metadata if available."""
        try:
            img = Image.open(path)
            exif = img._getexif() or {}
            tag_map = {ExifTags.TAGS.get(k): v for k, v in exif.items() if k in ExifTags.TAGS}
            dt_str = tag_map.get('DateTimeOriginal') or tag_map.get('DateTime')
            if dt_str:
                return datetime.strptime(dt_str, '%Y:%m:%d %H:%M:%S')
        except Exception:
            return None
        return None

    media_files = []
    seen_hashes = set()
    
    if not os.path.exists(folder_path):
        raise FileNotFoundError(f"Image folder not found: {folder_path}")
    
    # Scan main folder + VIDEOS subfolder
    folders_to_scan = [folder_path]
    videos_subfolder = os.path.join(folder_path, 'VIDEOS')
    if os.path.exists(videos_subfolder):
        folders_to_scan.append(videos_subfolder)
    
    for scan_folder in folders_to_scan:
        for filename in sorted(os.listdir(scan_folder)):
            filepath = os.path.join(scan_folder, filename)
            file_ext = filename.lower()
            
            # Check if it's an image
            if file_ext.endswith(SUPPORTED_EXTENSIONS):
                try:
                    # Verify it's a valid image and check for duplicates
                    file_hash = md5_for_file(filepath)
                    if file_hash in seen_hashes:
                        print(f"  Skipping duplicate: {filename}")
                        continue
                    seen_hashes.add(file_hash)

                    # Get EXIF date or file modification date
                    dt = parse_exif_datetime(filepath)
                    if dt is None:
                        dt = datetime.fromtimestamp(os.path.getmtime(filepath))

                    # Verify it's a valid image with HEIC support
                    try:
                        # Suppress PIL warnings
                        import warnings
                        warnings.filterwarnings('ignore', category=UserWarning)
                        
                        img = Image.open(filepath)
                        img.verify()
                        # Try to actually load it to catch corrupted files
                        img = Image.open(filepath)  # Need to reopen after verify
                        img.load()
                    except Exception as verify_error:
                        # If PIL verification fails, try HEIC conversion
                        if file_ext.endswith(('.heic', '.heif')):
                            if load_image_with_heic_support(filepath) is None:
                                raise ValueError("Could not convert HEIC")
                        else:
                            # For other formats, try one more time with OpenCV
                            test_img = cv2.imread(filepath)
                            if test_img is None:
                                raise ValueError(f"Corrupted or truncated image: {verify_error}")
                    
                    media_files.append((filepath, dt, 'image'))
                except Exception as e:
                    print(f"  ⚠ Skipping corrupted/invalid image {filename}")
            
            # Check if it's a video
            elif file_ext.endswith(SUPPORTED_VIDEO_EXTENSIONS):
                try:
                    # Get file modification date
                    dt = datetime.fromtimestamp(os.path.getmtime(filepath))
                    
                    # Try to verify it's a valid video
                    try:
                        clip = VideoFileClip(filepath)
                        # Check if it has video stream
                        if clip.w > 0 and clip.h > 0:
                            clip.close()
                            media_files.append((filepath, dt, 'video'))
                        else:
                            print(f"  ⚠ Skipping video with no valid stream: {filename}")
                    except Exception as e:
                        print(f"  ⚠ Skipping invalid video {filename}")
                except Exception as e:
                    print(f"  ⚠ Skipping video {filename}: {e}")
    
    if not media_files:
        raise ValueError(f"No valid images or videos found in {folder_path}")

    # Sort chronologically
    media_files.sort(key=lambda x: x[1])
    
    # Group media by date (YYYY-MM-DD)
    from collections import defaultdict
    grouped = defaultdict(list)
    for filepath, dt, media_type in media_files:
        date_key = dt.date()
        grouped[date_key].append((filepath, dt, media_type))
    
    # Sort each group chronologically by time (not just date)
    for date_key in grouped:
        grouped[date_key].sort(key=lambda x: x[1])
    
    # Convert to list of groups, sorted by date
    media_groups = [group for date_key in sorted(grouped.keys()) for group in [grouped[date_key]]]
    
    # Add date information to each group
    groups_with_dates = []
    for group in media_groups:
        date_key = group[0][1].date()  # Get date from first item
        groups_with_dates.append((group, date_key))
    
    total_media = len(media_files)
    total_groups = len(media_groups)
    image_count = sum(1 for _, _, mtype in media_files if mtype == 'image')
    video_count = sum(1 for _, _, mtype in media_files if mtype == 'video')
    collage_count = sum(1 for group in media_groups if len(group) > 1 and all(m[2] == 'image' for m in group))
    
    print(f"✓ Loaded {total_media} media files in {total_groups} date groups")
    print(f"  ({image_count} images, {video_count} videos, {collage_count} collage groups)")
    
    return groups_with_dates


def convert_heic_to_jpg(heic_path):
    """Convert HEIC image to JPG using ffmpeg, return numpy array."""
    try:
        # Use ffmpeg to convert HEIC to temporary JPG
        temp_jpg = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False).name
        ffmpeg_path = shutil.which('ffmpeg')
        if not ffmpeg_path:
            try:
                import imageio_ffmpeg
                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            except:
                return None
        
        if not ffmpeg_path:
            return None
        
        # Convert HEIC to JPG
        # Note: ffmpeg might struggle with Hebrew paths too, passing as input usually works better if quoted,
        # but pure python approaches are safer. Assuming ffmpeg handles it or user renames input if this fails.
        result = subprocess.run(
            [ffmpeg_path, '-i', heic_path, '-y', temp_jpg],
            capture_output=True,
            timeout=10
        )
        
        if result.returncode == 0 and os.path.exists(temp_jpg):
            # Read the converted JPG using safe reader
            img = read_image_safe(temp_jpg) # CHANGED THIS LINE
            # Clean up temp file
            try:
                os.remove(temp_jpg)
            except:
                pass
            return img
        else:
            try:
                os.remove(temp_jpg)
            except:
                pass
            return None
    except Exception as e:
        return None


def load_image_with_heic_support(filepath):
    """Load image with HEIC support using pillow-heif or ffmpeg fallback."""
    try:
        # Suppress warnings about truncated images
        import warnings
        warnings.filterwarnings('ignore', category=UserWarning)
        
        # Try PIL first (works if pillow-heif is installed) - PIL handles Hebrew paths correctly
        img = Image.open(filepath)
        img.load()
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    except Exception:
        # Fallback to ffmpeg conversion for HEIC
        if filepath.lower().endswith(('.heic', '.heif')):
            return convert_heic_to_jpg(filepath)
        return None

def resize_video_to_fit(video_path, target_width, target_height):
    """
    Load video, resize to fit target resolution while preserving original speed.
    Keeps videos at their natural playback speed to avoid artifacts.
    Returns None if video is corrupted/unreadable.
    """
    try:
        video_clip = VideoFileClip(video_path)
        
        # Remove audio to avoid conflicts with background music
        if video_clip.audio is not None:
            video_clip = video_clip.without_audio()
        
        # Check if video has valid dimensions
        if video_clip.w is None or video_clip.h is None or video_clip.w <= 0 or video_clip.h <= 0:
            print(f"  ⚠ Video has invalid dimensions: {video_clip.w}x{video_clip.h}")
            video_clip.close()
            return None
        
        # Resize to fit target size - maintain aspect ratio
        if video_clip.w / video_clip.h >= target_width / target_height:
            # Width is limiting
            video_clip = video_clip.resize(width=target_width)
        else:
            # Height is limiting
            video_clip = video_clip.resize(height=target_height)
        
        # Add black padding if needed (letterbox)
        if video_clip.w < target_width or video_clip.h < target_height:
            try:
                from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
                pad_h = max(0, target_height - video_clip.h)
                pad_w = max(0, target_width - video_clip.w)
                y_pad = pad_h // 2
                x_pad = pad_w // 2
                canvas = ColorClip(size=(target_width, target_height), color=(0, 0, 0))
                canvas = canvas.set_duration(video_clip.duration)
                # Use proper list syntax for CompositeVideoClip
                video_clip = CompositeVideoClip([canvas, video_clip.set_position((x_pad, y_pad))])
            except Exception as composite_error:
                print(f"  ⚠ Could not apply letterbox to video: {composite_error}")
                # Return the video without letterbox if composite fails
                return video_clip
        
        return video_clip
    except Exception as e:
        print(f"  ⚠ Error processing video {video_path}: {e}")
        return None


def resize_image_to_fit(image_path, target_width, target_height):
    """
    Load image and resize to fit target resolution.
    Maintains aspect ratio with black letterbox/pillarbox if needed.
    Supports HEIC with fallback conversion.
    Returns None if image is corrupted/unreadable.
    """
    try:
        # Suppress PIL warnings about truncated/corrupted images
        import warnings
        warnings.filterwarnings('ignore', category=UserWarning)
        
        # CHANGED: Use read_image_safe instead of cv2.imread
        img_bgr = read_image_safe(str(image_path))
        
        # If cv2 failed (or file implies HEIC), try pillow/HEIC conversion
        if img_bgr is None:
            img_bgr = load_image_with_heic_support(str(image_path))
        
        if img_bgr is None:
            return None
        
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        h, w = img_rgb.shape[:2]
        
        # Calculate scaling to fit image in target size (always fit inside, never bigger)
        scale_w = target_width / w
        scale_h = target_height / h
        scale = min(scale_w, scale_h)  # Use smaller scale to fit inside
        
        new_w = int(w * scale)
        new_h = int(h * scale)
        
        # Resize image
        resized = cv2.resize(img_rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
        
        # Create black canvas and center the image (letterbox)
        frame = np.zeros((target_height, target_width, 3), dtype=np.uint8)
        y_offset = max(0, (target_height - new_h) // 2)
        x_offset = max(0, (target_width - new_w) // 2)
        
        # Safe slicing - ensure we don't go out of bounds
        y_end = min(target_height, y_offset + new_h)
        x_end = min(target_width, x_offset + new_w)
        frame[y_offset:y_end, x_offset:x_end] = resized[0:y_end-y_offset, 0:x_end-x_offset]
        
        return frame
    except Exception as e:
        # Silently return None for corrupted images
        return None

def create_month_year_overlay_frame(date_obj, target_size):
    """Create a numpy array with month/year overlay on transparent background."""
    from PIL import ImageDraw, ImageFont
    
    # Create transparent background
    overlay = Image.new('RGBA', (target_size[0], target_size[1]), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Try to load configured font for dates
    try:
        font = ImageFont.truetype(DATE_FONT_PATH, DATE_FONT_SIZE)
    except:
        try:
            font = ImageFont.truetype("C:\\Windows\\Fonts\\trebuc.ttf", DATE_FONT_SIZE)
        except:
            font = ImageFont.load_default()
    
    # Format date as "January 2025" (in English)
    months_en = {
        1: 'January', 2: 'February', 3: 'March', 4: 'April',
        5: 'May', 6: 'June', 7: 'July', 8: 'August',
        9: 'September', 10: 'October', 11: 'November', 12: 'December'
    }
    month_name = months_en.get(date_obj.month, f"Month {date_obj.month}")
    year = date_obj.year
    
    text = f"{month_name} {year}"
    
    # Get text size
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # Position at bottom center
    x = (target_size[0] - text_width) // 2
    y = target_size[1] - text_height - 40  # 40 pixels from bottom
    
    # Draw semi-transparent background for text
    bg_padding = 20
    draw.rectangle(
        [(x - bg_padding, y - bg_padding), (x + text_width + bg_padding, y + text_height + bg_padding)],
        fill=(0, 0, 0, 150)  # Semi-transparent black
    )
    
    # Draw white text
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
    
    # Convert to numpy array (RGBA)
    return np.array(overlay)


def apply_month_overlay(frame, overlay_rgba):
    """Apply month/year overlay to an image frame - optimized version."""
    # Use NumPy vectorized operations instead of loops
    h, w = frame.shape[:2]
    
    # Extract alpha channel and normalize to 0-1
    overlay_alpha = overlay_rgba[:, :, 3].astype(np.float32) / 255.0
    overlay_rgb = overlay_rgba[:, :, :3].astype(np.float32)
    frame_float = frame.astype(np.float32)
    
    # Vectorized alpha blending for all channels at once
    for c in range(3):
        frame_float[:, :, c] = (frame_float[:, :, c] * (1 - overlay_alpha) + 
                                overlay_rgb[:, :, c] * overlay_alpha)
    
    return frame_float.astype(np.uint8)


def create_title_card(text, duration, target_size):
    """Create a simple title card with text."""
    from PIL import ImageDraw, ImageFont
    
    # Create black background
    card = Image.new('RGB', (target_size[0], target_size[1]), color=(0, 0, 0))
    draw = ImageDraw.Draw(card)
    
    # Try to load configured font
    try:
        font = ImageFont.truetype(TITLE_FONT_PATH, TITLE_FONT_SIZE)
    except:
        try:
            font = ImageFont.truetype("C:\\Windows\\Fonts\\trebuc.ttf", TITLE_FONT_SIZE)
        except:
            font = ImageFont.load_default()
    
    # Center text
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (target_size[0] - text_width) // 2
    y = (target_size[1] - text_height) // 2
    
    # Draw white text
    draw.text((x, y), text, fill=(255, 255, 255), font=font)
    
    # Convert to numpy array
    card_array = np.array(card)
    
    # Create clip without heavy fade effects (memory efficient)
    clip = ImageClip(card_array).set_duration(duration)
    return clip


def create_pause_clip(duration, target_size, fade_in=True, fade_out=True):
    """Create a black pause clip with fade effects."""
    # Create black frame
    black_frame = np.zeros((target_size[1], target_size[0], 3), dtype=np.uint8)
    
    # Create clip
    clip = ImageClip(black_frame).set_duration(duration)
    
    # Add fade effects
    if fade_in:
        clip = clip.crossfadein(1.0)  # 1 second fade in from black
    if fade_out:
        clip = clip.crossfadeout(1.0)  # 1 second fade out to black
    
    return clip


def calculate_input_hash(image_folder, audio_file, settings):
    """Calculate hash of all inputs to detect changes."""
    hasher = hashlib.md5()
    
    # Hash all image files (sorted by name)
    image_files = []
    for filename in sorted(os.listdir(image_folder)):
        if filename.lower().endswith(SUPPORTED_EXTENSIONS):
            filepath = os.path.join(image_folder, filename)
            image_files.append(filepath)
    
    for img_path in sorted(image_files):
        # Hash file path and file size
        hasher.update(img_path.encode())
        hasher.update(str(os.path.getsize(img_path)).encode())
        
        # Hash file content (full hash for consistent results)
        try:
            with open(img_path, 'rb') as f:
                file_hasher = hashlib.md5()
                while chunk := f.read(8192):
                    file_hasher.update(chunk)
                hasher.update(file_hasher.hexdigest().encode())
        except:
            pass
    
    # Hash audio file
    if os.path.exists(audio_file):
        hasher.update(audio_file.encode())
        hasher.update(str(os.path.getsize(audio_file)).encode())
        
        # Hash audio content
        try:
            with open(audio_file, 'rb') as f:
                file_hasher = hashlib.md5()
                while chunk := f.read(8192):
                    file_hasher.update(chunk)
                hasher.update(file_hasher.hexdigest().encode())
        except:
            pass
    
    # Hash settings
    hasher.update(json.dumps(settings, sort_keys=True).encode())
    
    return hasher.hexdigest()


def check_cache(output_file, current_hash):
    """Check if cached video exists and is up to date."""
    cache_file = output_file + '.cache'
    
    # Check if output video exists
    if not os.path.exists(output_file):
        return False
    
    # Check if cache metadata exists
    if not os.path.exists(cache_file):
        return False
    
    try:
        with open(cache_file, 'r') as f:
            cache_data = json.load(f)
        
        # Compare hashes
        if cache_data.get('hash') == current_hash:
            return True
    except:
        pass
    
    return False


def save_cache(output_file, input_hash):
    """Save cache metadata."""
    cache_file = output_file + '.cache'
    cache_data = {
        'hash': input_hash,
        'timestamp': datetime.now().isoformat(),
        'output_file': output_file
    }
    
    with open(cache_file, 'w') as f:
        json.dump(cache_data, f, indent=2)


def analyze_audio_tempo(audio_path):
    """Analyze audio file to detect tempo (BPM) and beat times."""
    try:
        print("  Analyzing audio tempo...")
        y, sr = librosa.load(audio_path)
        
        # Detect tempo and beat frames
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        
        # Convert beat frames to time in seconds
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        
        print(f"  ✓ Detected tempo: {tempo:.1f} BPM")
        print(f"  ✓ Found {len(beat_times)} beats")
        
        return tempo, beat_times
    except Exception as e:
        print(f"  ⚠ Could not analyze tempo: {e}")
        return None, None


def create_collage(media_group, target_size):
    """
    Create a collage from images.
    - 2 images: 1x2 grid (side by side, full height)
    - 3-4 images: 2x2 grid
    media_group is a list of (filepath, datetime, media_type) tuples.
    Only includes images, not videos.
    """
    # Get only images from the group
    images = [(path, dt) for path, dt, mtype in media_group if mtype == 'image']
    num_images = len(images)
    
    # Create canvas
    canvas = np.zeros((target_size[1], target_size[0], 3), dtype=np.uint8)
    
    if num_images == 2:
        # 1x2 grid - two images side by side (full height)
        cell_w = target_size[0] // 2
        cell_h = target_size[1]
        
        for idx, (image_path, _) in enumerate(images):
            col = idx
            
            # Load and resize image to fit cell
            frame = resize_image_to_fit(image_path, cell_w, cell_h)
            
            # Skip corrupted images
            if frame is None:
                continue
            
            # Crop to exact cell size
            frame_h, frame_w = frame.shape[:2]
            if frame_h >= cell_h and frame_w >= cell_w:
                frame_cell = frame[0:cell_h, 0:cell_w]
            else:
                frame_cell = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)
                frame_cell[0:frame_h, 0:frame_w] = frame[0:frame_h, 0:frame_w]
            
            # Place in canvas
            x0 = col * cell_w
            canvas[0:cell_h, x0:x0+cell_w] = frame_cell
    
    return canvas


def is_image_vertical(image_path):
    """Check if an image is vertical/portrait orientation.
    
    Returns:
        True if image is vertical (height > width), False otherwise
    """
    try:
        from PIL import Image, ExifTags
        img = Image.open(image_path)
        
        # Get actual dimensions after EXIF orientation is applied
        # PIL automatically handles EXIF orientation when loading
        width = img.width
        height = img.height
        
        # Handle EXIF orientation tag to get true orientation
        try:
            exif = img._getexif()
            if exif:
                for tag, value in exif.items():
                    if tag in ExifTags.TAGS and ExifTags.TAGS[tag] == 'Orientation':
                        # Orientations 6 and 8 are rotated 90/270 degrees
                        # In these cases, width and height are swapped in the file
                        if value in [6, 8]:
                            # Swap dimensions to get true orientation
                            width, height = height, width
        except:
            pass
        
        # Vertical/portrait if height > width
        return height > width
    except Exception as e:
        print(f"  ⚠ Could not check orientation for {image_path}: {e}")
        return False


def apply_random_transition(clip, transition_duration, transition_type=None):
    """Apply lightweight crossfade transition to a clip.
    Uses only clip.crossfadein() for efficient memory usage and smooth rendering.
    """
    try:
        return clip.crossfadein(transition_duration)
    except Exception as e:
        # Last resort: just return the clip as-is if transition fails
        return clip


def detect_faces_smart(image_path):
    """
    Smart multi-pass face detection using OpenCV Haar Cascade.
    Avoids both false positives (100+ faces) and false negatives (missing real faces).
    
    Strategy:
    1. Try balanced parameters (most common case)
    2. If 0-2 faces found: try looser params (might be missing people)
    3. If 30+ faces found: too many false positives, use stricter
    4. Return the result that makes most sense
    
    Returns:
        Dictionary with 'center', 'bbox', 'face_count' if faces found, None otherwise
    """
    try:
        # Load image with OpenCV
        img = read_image_safe(image_path)
        if img is None:
            return None
        
        # Convert to grayscale for face detection
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Load Haar Cascade classifier (built into OpenCV)
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        
        # Try THREE different parameter sets to find best balance
        # Balanced/Medium (most likely correct)
        faces_balanced = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=4,        # Medium sensitivity
            minSize=(40, 40),      # Medium face size
            flags=cv2.CASCADE_SCALE_IMAGE
        )
        
        # Loose (catch more faces, but allow more false positives)
        faces_loose = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.05,
            minNeighbors=3,        # More sensitive
            minSize=(30, 30),      # Smaller faces
            flags=cv2.CASCADE_SCALE_IMAGE
        )
        
        # Strict (avoid false positives, but may miss faces)
        faces_strict = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.15,
            minNeighbors=6,        # Stricter
            minSize=(55, 55),      # Larger faces only
            flags=cv2.CASCADE_SCALE_IMAGE
        )
        
        # Smart selection logic:
        # 1. If balanced has reasonable count (3-25) -> use it (best balance)
        # 2. If balanced is 0-2 but loose has more -> prefer loose (don't miss faces)
        # 3. If balanced is 30+ -> too many, use strict
        # 4. Otherwise use balanced (safest default)
        
        best_faces = faces_balanced
        
        if len(faces_balanced) == 0 and len(faces_loose) > 0:
            # No balanced detection but loose found some -> use loose
            best_faces = faces_loose
        elif len(faces_balanced) <= 2 and len(faces_loose) > len(faces_balanced) + 2:
            # Very few balanced but loose finds significantly more -> might be missing people
            # Only switch if difference is meaningful (3+ more faces)
            best_faces = faces_loose
        elif len(faces_balanced) > 30:
            # Too many detections = false positives, use strict
            best_faces = faces_strict
        
        # Final validation: if still unreasonable (>40 faces), force strict
        if len(best_faces) > 40:
            best_faces = faces_strict
        
        # Calculate bounding box that contains ALL detected faces
        if len(best_faces) > 0:
            # Find the bounding box that encompasses all faces
            min_x = min(x for (x, y, w, h) in best_faces)
            min_y = min(y for (x, y, w, h) in best_faces)
            max_x = max(x + w for (x, y, w, h) in best_faces)
            max_y = max(y + h for (x, y, w, h) in best_faces)
            
            # Calculate center of the combined bounding box
            center_x = (min_x + max_x) // 2
            center_y = (min_y + max_y) // 2
            
            # Add padding around faces (10% on each side)
            img_h, img_w = img.shape[:2]
            width = max_x - min_x
            height = max_y - min_y
            padding_x = int(width * 0.1)
            padding_y = int(height * 0.1)
            
            # Padded bounding box
            padded_min_x = max(0, min_x - padding_x)
            padded_min_y = max(0, min_y - padding_y)
            padded_max_x = min(img_w, max_x + padding_x)
            padded_max_y = min(img_h, max_y + padding_y)
            
            return {
                'center': (center_x, center_y),
                'bbox': (padded_min_x, padded_min_y, padded_max_x, padded_max_y),
                'face_count': len(best_faces)
            }
        
        return None
    
    except Exception as e:
        # If face detection fails, just return None
        return None


def detect_faces_quick(image_path):
    """Alias for backwards compatibility"""
    return detect_faces_smart(image_path)


def create_2x2_grid_clip(image_paths, duration, target_size, transition_duration):
    """Create a 2x2 grid clip from 4 images.
    Shows FULL image in each quadrant with letterbox/pillarbox (CONTAIN mode).
    No cropping - all content visible.
    
    Args:
        image_paths: List of 2-4 image paths (will pad with black if less than 4)
        duration: Duration for the grid clip
        target_size: (width, height) tuple for the final video
        transition_duration: Duration for crossfade effect
    
    Returns:
        ImageClip with 4 images arranged in 2x2 grid (full images, no crop)
    """
    from PIL import Image
    
    # Target size for each quadrant (half width, half height)
    quad_w = target_size[0] // 2
    quad_h = target_size[1] // 2
    
    # Create blank canvas
    grid_image = Image.new('RGB', (target_size[0], target_size[1]), color=(0, 0, 0))
    
    # Positions for 2x2 grid: top-left, top-right, bottom-left, bottom-right
    positions = [
        (0, 0),           # Top-left
        (quad_w, 0),      # Top-right
        (0, quad_h),      # Bottom-left
        (quad_w, quad_h)  # Bottom-right
    ]
    
    # Load and place up to 4 images
    for i, img_path in enumerate(image_paths[:4]):
        if i >= 4:
            break
            
        try:
            # Load image
            img = Image.open(img_path)
            
            # Handle orientation from EXIF
            try:
                from PIL import ExifTags
                exif = img._getexif()
                if exif:
                    for tag, value in exif.items():
                        if tag in ExifTags.TAGS and ExifTags.TAGS[tag] == 'Orientation':
                            if value == 3:
                                img = img.rotate(180, expand=True)
                            elif value == 6:
                                img = img.rotate(270, expand=True)
                            elif value == 8:
                                img = img.rotate(90, expand=True)
            except:
                pass
            
            # Convert to RGB if needed
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # FIT image into quadrant (CONTAIN mode - shows entire image)
            # This displays the FULL image with letterbox/pillarbox, no cropping
            img_aspect = img.width / img.height
            quad_aspect = quad_w / quad_h
            
            if img_aspect > quad_aspect:
                # Image is wider than quadrant - fit by width
                new_w = quad_w
                new_h = int(new_w / img_aspect)
            else:
                # Image is taller than quadrant - fit by height
                new_h = quad_h
                new_w = int(new_h * img_aspect)
            
            # Resize image to fit
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            # Create a black quadrant background
            quadrant = Image.new('RGB', (quad_w, quad_h), color=(0, 0, 0))
            
            # Center the fitted image in the quadrant (letterbox/pillarbox)
            offset_x = (quad_w - new_w) // 2
            offset_y = (quad_h - new_h) // 2
            
            # Paste the fitted image onto the black background
            quadrant.paste(img, (offset_x, offset_y))
            
            # Paste the complete quadrant into grid
            grid_image.paste(quadrant, positions[i])
            
        except Exception as e:
            print(f"  ⚠ Error loading image for grid {img_path}: {e}")
            # Leave black quadrant on error
            pass
    
    # Convert to numpy array and create clip
    grid_array = np.array(grid_image)
    clip = ImageClip(grid_array).set_duration(duration)
    
    # Apply transition
    clip = apply_random_transition(clip, transition_duration)
    
    return clip


def create_1x3_vertical_grid(image_paths, duration, target_size, transition_duration):
    """Create a 1x3 grid clip from 3 vertical images (side by side).
    
    Args:
        image_paths: List of 3 vertical image paths
        duration: Duration for the grid clip
        target_size: (width, height) tuple for the final video
        transition_duration: Duration for crossfade effect
    
    Returns:
        ImageClip with 3 vertical images arranged horizontally (1x3 grid)
    """
    from PIL import Image
    
    # Each vertical image gets 1/3 of the width, full height
    slot_w = target_size[0] // 3
    slot_h = target_size[1]
    
    # Create blank canvas
    grid_image = Image.new('RGB', (target_size[0], target_size[1]), color=(0, 0, 0))
    
    # Positions for 1x3 grid: left, center, right
    positions = [
        (0, 0),              # Left
        (slot_w, 0),         # Center
        (slot_w * 2, 0)      # Right
    ]
    
    # Load and place up to 3 images
    for i, img_path in enumerate(image_paths[:3]):
        if i >= 3:
            break
            
        try:
            # Load image
            img = Image.open(img_path)
            
            # Handle orientation from EXIF
            try:
                from PIL import ExifTags
                exif = img._getexif()
                if exif:
                    for tag, value in exif.items():
                        if tag in ExifTags.TAGS and ExifTags.TAGS[tag] == 'Orientation':
                            if value == 3:
                                img = img.rotate(180, expand=True)
                            elif value == 6:
                                img = img.rotate(270, expand=True)
                            elif value == 8:
                                img = img.rotate(90, expand=True)
            except:
                pass
            
            # Convert to RGB if needed
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # DETECT FACES in this vertical image for quality assurance
            face_data = detect_faces_quick(img_path)
            if face_data:
                face_count = face_data['face_count']
                print(f"    Vertical image {i+1}: {face_count} face(s) detected ✓")
            else:
                print(f"    Vertical image {i+1}: No faces detected (portrait/object image)")
            
            # Calculate scaling to FIT slot (CONTAIN, not COVER)
            # This shows the ENTIRE image without cropping
            img_aspect = img.width / img.height
            slot_aspect = slot_w / slot_h
            
            if img_aspect > slot_aspect:
                # Image is wider - fit by width
                new_w = slot_w
                new_h = int(new_w / img_aspect)
            else:
                # Image is taller - fit by height
                new_h = slot_h
                new_w = int(new_h * img_aspect)
            
            # Resize image to fit
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            # Create a black slot background
            slot_image = Image.new('RGB', (slot_w, slot_h), color=(0, 0, 0))
            
            # Center the fitted image in the slot (letterbox/pillarbox)
            offset_x = (slot_w - new_w) // 2
            offset_y = (slot_h - new_h) // 2
            
            # Paste the fitted image onto the black background
            slot_image.paste(img, (offset_x, offset_y))
            
            # Paste the complete slot into grid
            grid_image.paste(slot_image, positions[i])
            
        except Exception as e:
            print(f"  ⚠ Error loading image for 1x3 grid {img_path}: {e}")
            # Leave black slot on error
            pass
    
    # Convert to numpy array and create clip
    grid_array = np.array(grid_image)
    clip = ImageClip(grid_array).set_duration(duration)
    
    # Apply transition
    clip = apply_random_transition(clip, transition_duration)
    
    return clip


def create_slideshow_clips(media_groups_with_dates, duration_per_weight, target_size, transition_duration, beat_times=None, beats_per_image=None):
    """
    Creates clips from IMAGES ONLY with weighted durations.
    Updates: Different display types get different durations.
    Grid (2x2) gets GRID_WEIGHT * duration_per_weight
    Collage (1x2) gets COLLAGE_WEIGHT * duration_per_weight
    Single (1x1) gets SINGLE_WEIGHT * duration_per_weight
    """
    image_clips = []
    video_clips = [] 
    
    image_count_total = sum(1 for group, _ in media_groups_with_dates for item in group if item[2] == 'image')
    image_count_used = 0
    
    print(f"\nCreating slideshow with weighted durations...")
    
    for group_idx, (media_group, date_key) in enumerate(media_groups_with_dates):
        
        images = [item for item in media_group if item[2] == 'image']
        
        if not images:
            continue

        if USE_GRID_2X2:
            horizontal = [img for img in images if not is_image_vertical(img[0])]
            vertical = [img for img in images if is_image_vertical(img[0])]
            
            # --- 1. Horizontal Logic (Sets of 4) ---
            for i in range(0, len(horizontal), 4):
                batch = horizontal[i:i+4]
                if len(batch) >= 4:
                    image_paths = [img[0] for img in batch[:4]]
                    grid_duration = duration_per_weight * GRID_WEIGHT
                    try:
                        clip = create_2x2_grid_clip(image_paths, grid_duration, target_size, transition_duration)
                        image_clips.append(clip)
                        image_count_used += 4
                    except: pass
                elif len(batch) == 2:
                    collage = create_collage(batch, target_size)
                    collage_duration = duration_per_weight * COLLAGE_WEIGHT
                    clip = ImageClip(collage).set_duration(collage_duration)
                    clip = apply_random_transition(clip, transition_duration)
                    image_clips.append(clip)
                    image_count_used += 2
                else:
                    # 1 or 3 images -> singles
                    single_duration = duration_per_weight * SINGLE_WEIGHT
                    for img in batch:
                        frame = resize_image_to_fit(img[0], target_size[0], target_size[1])
                        if frame is not None:
                            clip = ImageClip(frame).set_duration(single_duration)
                            clip = apply_random_transition(clip, transition_duration)
                            image_clips.append(clip)
                            image_count_used += 1

            # --- 2. Vertical Logic - Grid 1x3, 1x2, or 1x1 ---
            # Vertical images (Portrait) in pairs -> Collage 1x2
            # Never use 2x2 grid as it crops them incorrectly
            for i in range(0, len(vertical), 2):
                batch = vertical[i:i+2]
                if len(batch) == 2:
                    # Pair of vertical images -> 1x2 Collage (side by side)
                    collage = create_collage(batch, target_size)
                    collage_duration = duration_per_weight * COLLAGE_WEIGHT
                    clip = ImageClip(collage).set_duration(collage_duration)
                    clip = apply_random_transition(clip, transition_duration)
                    image_clips.append(clip)
                    image_count_used += 2
                else:
                    # Single image -> 1x1
                    single_duration = duration_per_weight * SINGLE_WEIGHT
                    for img in batch:
                        frame = resize_image_to_fit(img[0], target_size[0], target_size[1])
                        if frame is not None:
                            clip = ImageClip(frame).set_duration(single_duration)
                            clip = apply_random_transition(clip, transition_duration)
                            image_clips.append(clip)
                            image_count_used += 1
        
        else:
            # Non-grid logic (default)
            collage_duration = duration_per_weight * COLLAGE_WEIGHT
            single_duration = duration_per_weight * SINGLE_WEIGHT
            if len(images) == 2:
                collage = create_collage(images, target_size)
                clip = ImageClip(collage).set_duration(collage_duration)
                clip = apply_random_transition(clip, transition_duration)
                image_clips.append(clip)
                image_count_used += len(images)
            else:
                for img in images:
                    frame = resize_image_to_fit(img[0], target_size[0], target_size[1])
                    if frame is not None:
                        clip = ImageClip(frame).set_duration(single_duration)
                        clip = apply_random_transition(clip, transition_duration)
                        image_clips.append(clip)
                        image_count_used += 1
        
    print(f"\n✓ Generated {len(image_clips)} weighted image clips (Videos skipped)")
    print(f"  Total images used: {image_count_used}/{image_count_total}")
    
    return image_clips, video_clips, image_count_used, image_count_total


def compose_final_video(image_clips, video_clips, audio_path, output_path, target_size, intro_clip=None, outro_clip=None, opening_pause=None, closing_pause=None):
    """Render final video with images synced to audio, excluding outro and closing_pause from audio sync."""
    print("\nComposing final video...")
    
    # Load audio to get exact duration
    audio = AudioFileClip(audio_path)
    audio_duration = audio.duration
    
    # Build the audio-synced section (opening_pause + intro + image_clips)
    # This section MUST fit within the audio duration
    audio_synced_clips = []
    if opening_pause is not None:
        audio_synced_clips.append(opening_pause)
    if intro_clip is not None:
        audio_synced_clips.append(intro_clip)
    audio_synced_clips.extend(image_clips)
    
    audio_synced_video = concatenate_videoclips(audio_synced_clips, method="chain") if audio_synced_clips else None
    audio_synced_duration = audio_synced_video.duration if audio_synced_video is not None else 0
    
    # Adjust audio-synced section to fit within audio duration
    if audio_synced_video is not None:
        if audio_synced_duration < audio_duration:
            print(f"  Audio-synced section is {audio_duration - audio_synced_duration:.1f}s shorter than audio")
            print(f"  Padding with black to match audio...")
            padding_duration = audio_duration - audio_synced_duration
            black_frame = np.zeros((target_size[1], target_size[0], 3), dtype=np.uint8)
            padding_clip = ImageClip(black_frame).set_duration(padding_duration)
            audio_synced_video = concatenate_videoclips([audio_synced_video, padding_clip], method="chain")
            audio_synced_duration = audio_duration
        elif audio_synced_duration > audio_duration:
            print(f"  Audio-synced section is {audio_synced_duration - audio_duration:.1f}s longer than audio")
            print(f"  Trimming audio-synced section to match audio...")
            audio_synced_video = audio_synced_video.subclip(0, audio_duration)
            audio_synced_duration = audio_duration
        
        # Apply audio to the synced section
        audio_synced_video = audio_synced_video.set_audio(audio)
    
    # Build the outro section (outro + closing_pause) - these play WITHOUT audio
    outro_section_clips = []
    if outro_clip is not None:
        outro_section_clips.append(outro_clip)
    if closing_pause is not None:
        outro_section_clips.append(closing_pause)
    
    outro_section = concatenate_videoclips(outro_section_clips, method="chain") if outro_section_clips else None
    
    # Combine final: audio-synced section + outro section (NO videos, as per requirement)
    if audio_synced_video and outro_section:
        final_video = concatenate_videoclips([audio_synced_video, outro_section], method="chain")
    else:
        final_video = audio_synced_video or outro_section
    
    total_duration = final_video.duration if final_video is not None else 0

    # Detect best codec
    codec = get_best_video_codec()
    
    print(f"Rendering to: {output_path}")
    print(f"Total duration: {total_duration:.2f}s")
    print(f"Codec: {codec}")
    
    # Render with best available codec
    if codec == 'h264_nvenc':
        # NVIDIA H.264 encoding - uses less VRAM
        print("Using NVIDIA H.264 GPU (h264_nvenc) - lower memory usage...")
        final_video.write_videofile(
            output_path,
            fps=VIDEO_FPS,
            codec=codec,
            audio_codec='aac',
            bitrate=VIDEO_BITRATE,
            ffmpeg_params=[
                '-preset', 'fast',  # fast, default, slow
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart',
                '-rc:v', 'vbr',
                '-cq:v', str(VIDEO_QUALITY),
                '-b_ref_mode', 'disabled',  # Reduce memory usage
            ],
            verbose=False,
            logger=None,
        )
    elif codec == 'hevc_nvenc':
        # NVIDIA HEVC encoding
        print("Using NVIDIA HEVC GPU (hevc_nvenc)...")
        final_video.write_videofile(
            output_path,
            fps=VIDEO_FPS,
            codec=codec,
            audio_codec='aac',
            bitrate=VIDEO_BITRATE,
            ffmpeg_params=[
                '-preset', 'fast',
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart',
                '-rc:v', 'vbr',
                '-cq:v', str(VIDEO_QUALITY),
            ],
            verbose=False,
            logger=None,
        )
    else:
        # CPU fallback
        print("Using CPU encoding (libx264 ultrafast)...")
        final_video.write_videofile(
            output_path,
            fps=VIDEO_FPS,
            codec='libx264',
            audio_codec='aac',
            bitrate=VIDEO_BITRATE,
            preset='ultrafast',
            ffmpeg_params=[
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart',
                '-threads', '4',
                '-crf', str(VIDEO_QUALITY),
            ],
            verbose=False,
            logger=None,
        )
    
    if final_video:
        final_video.close()
    audio.close()
    
    print(f"\n✓ Video created: {output_path}")


def calculate_exact_slide_duration(media_groups, audio_duration, use_grid):
    """
    Calculates duration for IMAGES ONLY using weighted slide calculation.
    Updates: Different display types (Grid/Collage/Single) get different durations.
    Grid (4 images) > Collage (2 images) > Single (1 image)
    """
    total_weighted_slides = 0.0
    
    # Intro time and pause (defined in configuration)
    intro_time = FIXED_INTRO_TIME
    
    print("  Calculating timing with display type weights...")
    
    for group, _ in media_groups:
        images = [item for item in group if item[2] == 'image']
        if not images:
            continue
            
        if use_grid:
            horizontal = [img for img in images if not is_image_vertical(img[0])]
            vertical = [img for img in images if is_image_vertical(img[0])]
            
            # --- Calculate Horizontal images ---
            h_grids = len(horizontal) // 4
            h_remainder = len(horizontal) % 4
            total_weighted_slides += h_grids * GRID_WEIGHT
            
            if h_remainder == 2:
                total_weighted_slides += COLLAGE_WEIGHT
            else:
                total_weighted_slides += h_remainder * SINGLE_WEIGHT

            # --- Calculate Vertical images - Pairs 1x2 or 1x1 ---
            # Vertical images (Portrait) in pairs as 1x2 collage
            # Never use 2x2 grid as it crops them incorrectly
            v_pairs = len(vertical) // 2
            v_remainder = len(vertical) % 2
            total_weighted_slides += v_pairs * COLLAGE_WEIGHT  # זוגות אנכיים
            
            if v_remainder == 1:
                total_weighted_slides += SINGLE_WEIGHT   # תמונה בודדת
                
        else:
            # לוגיקה רגילה (ללא גריד)
            if len(images) == 2:
                total_weighted_slides += COLLAGE_WEIGHT
            else:
                total_weighted_slides += len(images) * SINGLE_WEIGHT

    available_time_for_images = audio_duration - intro_time
    
    if available_time_for_images <= 0:
        print("  ⚠ Warning: Audio is too short for Intro!")
        return 2.0 
        
    if total_weighted_slides == 0:
        return 3.0 
    
    # Division: available time / total weights
    duration_per_weight = available_time_for_images / total_weighted_slides
    
    print(f"  ✓ Audio duration: {audio_duration:.2f}s")
    print(f"  ✓ Reserved for Intro/Pause: {intro_time:.2f}s")
    print(f"  ✓ Time available for images: {available_time_for_images:.2f}s")
    print(f"  ✓ Total weighted slides: {total_weighted_slides:.1f}")
    print(f"  ✓ Duration per weight unit: {duration_per_weight:.2f}s")
    print(f"    - Grid (2x2 horizontal): {duration_per_weight * GRID_WEIGHT:.2f}s")
    print(f"    - Grid (1x3 vertical): {duration_per_weight * TRIPLE_WEIGHT:.2f}s")
    print(f"    - Collage (1x2): {duration_per_weight * COLLAGE_WEIGHT:.2f}s")
    print(f"    - Single (1x1): {duration_per_weight * SINGLE_WEIGHT:.2f}s")
    
    return duration_per_weight


def calculate_total_weighted_slides(media_groups, use_grid):
    """Compute total weighted slides to estimate timing when no audio is provided."""
    total_weighted_slides = 0.0
    for group, _ in media_groups:
        images = [item for item in group if item[2] == 'image']
        if not images:
            continue

        if use_grid:
            horizontal = [img for img in images if not is_image_vertical(img[0])]
            vertical = [img for img in images if is_image_vertical(img[0])]

            h_grids = len(horizontal) // 4
            h_remainder = len(horizontal) % 4
            total_weighted_slides += h_grids * GRID_WEIGHT

            if h_remainder == 2:
                total_weighted_slides += COLLAGE_WEIGHT
            else:
                total_weighted_slides += h_remainder * SINGLE_WEIGHT

            for i in range(0, len(vertical), 2):
                batch = vertical[i:i+2]
                if len(batch) == 2:
                    total_weighted_slides += COLLAGE_WEIGHT
                else:
                    total_weighted_slides += SINGLE_WEIGHT * len(batch)
        else:
            if len(images) == 2:
                total_weighted_slides += COLLAGE_WEIGHT
            else:
                total_weighted_slides += SINGLE_WEIGHT * len(images)

    return total_weighted_slides


def create_mixed_audio(audio_paths, fade_duration=3.0):
    """
    Create a mixed audio track from multiple audio files with smooth crossfading.
    
    Args:
        audio_paths: List of paths to audio files
        fade_duration: Duration of crossfade overlap between tracks (seconds)
    
    Returns:
        AudioFileClip: Mixed audio with crossfades
    """
    if not audio_paths:
        raise ValueError("No audio paths provided")
    
    if len(audio_paths) == 1:
        # Single audio file - just return it
        return AudioFileClip(audio_paths[0])
    
    print(f"\n{'='*70}")
    print(f"  AUDIO CROSSFADING")
    print(f"{'='*70}")
    print(f"Number of audio tracks: {len(audio_paths)}")
    print(f"Crossfade duration: {fade_duration}s")
    
    # Load all audio clips
    audio_clips = []
    total_duration = 0
    
    for i, path in enumerate(audio_paths):
        try:
            clip = AudioFileClip(path)
            audio_clips.append(clip)
            print(f"  Track {i+1}: {os.path.basename(path)} - Duration: {clip.duration:.2f}s")
            total_duration += clip.duration
        except Exception as e:
            print(f"  ⚠ Warning: Could not load audio {i+1}: {e}")
            continue
    
    if not audio_clips:
        raise ValueError("No valid audio clips could be loaded")
    
    if len(audio_clips) == 1:
        return audio_clips[0]
    
    # Calculate positions with crossfade overlaps
    positioned_clips = []
    current_time = 0
    
    for i, clip in enumerate(audio_clips):
        if i == 0:
            # First clip: fade out at the end
            faded_clip = clip.audio_fadeout(fade_duration)
            positioned_clips.append(faded_clip.set_start(current_time))
            current_time += clip.duration - fade_duration
        elif i == len(audio_clips) - 1:
            # Last clip: fade in at the beginning
            faded_clip = clip.audio_fadein(fade_duration)
            positioned_clips.append(faded_clip.set_start(current_time))
            current_time += clip.duration
        else:
            # Middle clips: fade in and fade out
            faded_clip = clip.audio_fadein(fade_duration).audio_fadeout(fade_duration)
            positioned_clips.append(faded_clip.set_start(current_time))
            current_time += clip.duration - fade_duration
    
    # Composite all clips
    mixed_audio = CompositeAudioClip(positioned_clips)
    
    # Set fps from the first clip (required for write_audiofile)
    mixed_audio.fps = audio_clips[0].fps
    
    final_duration = current_time
    print(f"\n  ✓ Original total duration: {total_duration:.2f}s")
    print(f"  ✓ Mixed duration with crossfades: {final_duration:.2f}s")
    print(f"  ✓ Time saved by crossfading: {total_duration - final_duration:.2f}s")
    print(f"{'='*70}\n")
    
    return mixed_audio


def main():
    """Main function to create simple slideshow video."""
    import time
    
    try:
        print("\n" + "=" * 70)
        print("  SIMPLE VIDEO SLIDESHOW CREATOR")
        print("=" * 70 + "\n")
        
        start_time = time.time()
        
        # Check cache first
        print("Step 0: Checking cache...")
        if not USE_CACHE:
            print("  Cache disabled by configuration")
        
        settings = {
            'width': TARGET_WIDTH,
            'height': TARGET_HEIGHT,
            'transition': TRANSITION_DURATION,
            'intro': INTRO_TEXT,
            'outro': OUTRO_TEXT,
            'use_grid_2x2': USE_GRID_2X2,
            'fixed_intro_time': FIXED_INTRO_TIME,
            'fps': VIDEO_FPS,
            'bitrate': VIDEO_BITRATE,
        }
        current_hash = calculate_input_hash(IMAGE_FOLDER_PATH, AUDIO_FILE_PATH, settings)
        
        if USE_CACHE and check_cache(OUTPUT_FILE_PATH, current_hash):
            print(f"✓ Cache is valid! Using existing video: {OUTPUT_FILE_PATH}")
            if os.path.exists(OUTPUT_FILE_PATH):
                file_size_mb = os.path.getsize(OUTPUT_FILE_PATH) / (1024**2)
                print(f"  File size: {file_size_mb:.1f} MB")
            print("\n" + "=" * 70)
            print("✓ NO PROCESSING NEEDED - VIDEO IS UP TO DATE!")
            print("=" * 70 + "\n")
            return
        else:
            print("✓ Cache invalid or missing, will create new video")
        print()
        
        # Load images and videos
        print("Step 1: Loading media...")
        media_groups = load_and_sort_images(IMAGE_FOLDER_PATH)
        print()
        
        # Analyze audio for tempo
        print("Step 2: Analyzing audio...")
        audio = AudioFileClip(AUDIO_FILE_PATH)
        audio_duration = audio.duration
        audio.close()
        
        # Calculate exact timing based on display type weights (Grid > Collage > Single)
        print("Step 2.5: Calculating exact timing with display type weights...")
        duration_per_weight = calculate_exact_slide_duration(media_groups, audio_duration, USE_GRID_2X2)
        print()
        
        # Create clips
        print("Step 3: Creating clips...")
        target_size = (TARGET_WIDTH, TARGET_HEIGHT)
        image_clips, video_clips, image_count_used, image_count_total = create_slideshow_clips(
            media_groups,
            duration_per_weight,
            target_size,
            TRANSITION_DURATION
        )
        
        # Verify all images were included
        print(f"\n{'='*70}")
        print(f"  IMAGE VERIFICATION")
        print(f"{'='*70}")
        print(f"Total images loaded: {image_count_total}")
        print(f"Total images used:   {image_count_used}")
        if image_count_used == image_count_total:
            print(f"✓ SUCCESS: All {image_count_total} images were included in the slideshow!")
        else:
            missing_count = image_count_total - image_count_used
            print(f"⚠ WARNING: {missing_count} image(s) were NOT included in the slideshow!")
        print(f"{'='*70}\n")
        print()
        
        # Detect available codecs
        print("Step 4: Detecting hardware...")
        get_best_video_codec()
        print()
        
        # Create title cards
        print("Step 5: Creating title cards...")
        intro_clip = create_title_card(INTRO_TEXT, 2.5, target_size) if INTRO_TEXT else None
        outro_clip = create_title_card(OUTRO_TEXT, 2.5, target_size) if OUTRO_TEXT else None
        if intro_clip:
            print("✓ Intro card created")
        if outro_clip:
            print("✓ Outro card created")
        
        # Create opening and closing pause clips with effects
        print("✓ Creating opening pause (5s with fade in effect)...")
        opening_pause = create_pause_clip(5.0, target_size, fade_in=True, fade_out=False)
        print("✓ Creating closing pause (5s with fade out effect)...")
        closing_pause = create_pause_clip(5.0, target_size, fade_in=False, fade_out=True)
        print()
        
        # Render video
        print("Step 6: Rendering video...")
        render_start = time.time()
        compose_final_video(image_clips, video_clips, AUDIO_FILE_PATH, OUTPUT_FILE_PATH, target_size, intro_clip, outro_clip, opening_pause, closing_pause)
        render_time = time.time() - render_start
        
        total_time = time.time() - start_time
        
        # Save cache
        save_cache(OUTPUT_FILE_PATH, current_hash)
        print("✓ Cache saved")
        
        print()
        print("=" * 70)
        print("✓ VIDEO CREATED SUCCESSFULLY!")
        print("=" * 70)
        print(f"Total time: {total_time:.1f}s ({total_time/60:.1f} minutes)")
        print(f"Rendering time: {render_time:.1f}s")
        
        if os.path.exists(OUTPUT_FILE_PATH):
            file_size_mb = os.path.getsize(OUTPUT_FILE_PATH) / (1024**2)
            print(f"File size: {file_size_mb:.1f} MB")
        print("=" * 70 + "\n")
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()


def generate_video_from_web(image_folder, audio_paths, output_path, intro_text, outro_text, config=None):
    """
    Wrapper function to be called from Flask.
    Returns (success: bool, message: str)
    
    Args:
        image_folder: Path to folder containing images
        audio_paths: List of paths to audio files (will be crossfaded)
        output_path: Path where video will be saved
        intro_text: Opening title text
        outro_text: Closing title text
        config: Dictionary with configuration parameters
    """
    print(f"Starting video generation...")
    
    # Update global settings
    global IMAGE_FOLDER_PATH, AUDIO_FILE_PATH, OUTPUT_FILE_PATH, INTRO_TEXT, OUTRO_TEXT
    global TARGET_WIDTH, TARGET_HEIGHT, TRANSITION_DURATION, USE_GRID_2X2
    global GRID_WEIGHT, COLLAGE_WEIGHT, TRIPLE_WEIGHT, SINGLE_WEIGHT
    global VIDEO_FPS, VIDEO_BITRATE, VIDEO_QUALITY, OPENING_PAUSE_DURATION, CLOSING_PAUSE_DURATION
    global INTRO_CARD_DURATION, OUTRO_CARD_DURATION, TITLE_FONT_SIZE, DATE_FONT_SIZE, MAX_IMAGE_WIDTH
    global TITLE_FONT_PATH, DATE_FONT_PATH
    
    IMAGE_FOLDER_PATH = image_folder
    OUTPUT_FILE_PATH = output_path
    INTRO_TEXT = intro_text
    OUTRO_TEXT = outro_text
    
    # Get crossfade duration from config
    crossfade_duration = 3.0
    if config:
        crossfade_duration = config.get('audio_crossfade', 3.0)
    
    # Apply configuration if provided
    if config:
        TARGET_WIDTH = config.get('target_width', TARGET_WIDTH)
        TARGET_HEIGHT = config.get('target_height', TARGET_HEIGHT)
        TRANSITION_DURATION = config.get('transition_duration', TRANSITION_DURATION)
        INTRO_CARD_DURATION = config.get('intro_card_duration', INTRO_CARD_DURATION)
        OUTRO_CARD_DURATION = config.get('outro_card_duration', OUTRO_CARD_DURATION)
        OPENING_PAUSE_DURATION = config.get('opening_pause', OPENING_PAUSE_DURATION)
        CLOSING_PAUSE_DURATION = config.get('closing_pause', CLOSING_PAUSE_DURATION)
        
        # Layout modes - USE_GRID_2X2 will be True if any grid mode is enabled
        USE_GRID_2X2 = config.get('enable_grid_2x2', True) or config.get('enable_grid_1x3', True)
        
        GRID_WEIGHT = config.get('grid_weight', GRID_WEIGHT)
        COLLAGE_WEIGHT = config.get('collage_weight', COLLAGE_WEIGHT)
        TRIPLE_WEIGHT = config.get('triple_weight', TRIPLE_WEIGHT)
        SINGLE_WEIGHT = config.get('single_weight', SINGLE_WEIGHT)
        VIDEO_FPS = config.get('video_fps', VIDEO_FPS)
        VIDEO_BITRATE = config.get('video_bitrate', VIDEO_BITRATE)
        VIDEO_QUALITY = config.get('video_quality', VIDEO_QUALITY)
        TITLE_FONT_SIZE = config.get('title_font_size', TITLE_FONT_SIZE)
        DATE_FONT_SIZE = config.get('date_font_size', DATE_FONT_SIZE)
        MAX_IMAGE_WIDTH = config.get('max_image_width', MAX_IMAGE_WIDTH)
        
        # Font selection (supports Google Fonts download and local assets/fonts)
        font_file = config.get('font_family', 'trebucbd.ttf')
        resolved_font = resolve_font_path(font_file)
        if resolved_font:
            TITLE_FONT_PATH = resolved_font
            DATE_FONT_PATH = resolved_font
    
    try:
        import time
        start_time = time.time()
        
        # Step 1: Loading
        print("Step 1: Loading media...")
        media_groups = load_and_sort_images(IMAGE_FOLDER_PATH)
        total_weighted_slides = calculate_total_weighted_slides(media_groups, USE_GRID_2X2)
        
        # Step 2: Audio - Create mixed audio with crossfading (or silent fallback)
        print("Step 2: Creating mixed audio with crossfading...")
        temp_audio_path = os.path.join(os.path.dirname(OUTPUT_FILE_PATH), 'temp_mixed_audio.mp3')
        try:
            if audio_paths:
                mixed_audio = create_mixed_audio(audio_paths, fade_duration=crossfade_duration)
            else:
                raise ValueError("No audio paths provided")
        except Exception as e:
            fallback_duration_per_weight = config.get('silent_duration_per_weight', 3.0) if config else 3.0
            intro_time = FIXED_INTRO_TIME
            estimated_duration = max(intro_time + total_weighted_slides * fallback_duration_per_weight, intro_time + fallback_duration_per_weight)
            print(f"  ⚠ Audio unavailable ({e}); using silent track ({estimated_duration:.1f}s)")
            mixed_audio = AudioClip(lambda t: 0.0, duration=estimated_duration, fps=44100)
        audio_duration = mixed_audio.duration
        
        # Save mixed audio temporarily for compose_final_video
        mixed_audio.write_audiofile(temp_audio_path, verbose=False, logger=None)
        AUDIO_FILE_PATH = temp_audio_path
        
        # Step 3: Timing
        print("Step 3: Calculating exact timing...")
        duration_per_weight = calculate_exact_slide_duration(media_groups, audio_duration, USE_GRID_2X2)
        
        # Step 4: Creating clips
        print("Step 4: Creating clips...")
        target_size = (TARGET_WIDTH, TARGET_HEIGHT)
        image_clips, video_clips, _, _ = create_slideshow_clips(
            media_groups, duration_per_weight, target_size, TRANSITION_DURATION
        )
        
        # Step 5: Titles & Pause
        print("Step 5: Creating title cards...")
        intro_clip = create_title_card(INTRO_TEXT, INTRO_CARD_DURATION, target_size) if INTRO_TEXT else None
        outro_clip = create_title_card(OUTRO_TEXT, OUTRO_CARD_DURATION, target_size) if OUTRO_TEXT else None
        opening_pause = create_pause_clip(OPENING_PAUSE_DURATION, target_size, fade_in=True, fade_out=False)
        closing_pause = create_pause_clip(CLOSING_PAUSE_DURATION, target_size, fade_in=False, fade_out=True)
        
        # Step 6: Rendering
        print("Step 6: Rendering video...")
        compose_final_video(image_clips, video_clips, AUDIO_FILE_PATH, OUTPUT_FILE_PATH, target_size, intro_clip, outro_clip, opening_pause, closing_pause)
        
        # Cleanup temporary audio file
        if os.path.exists(temp_audio_path):
            try:
                mixed_audio.close()
                os.remove(temp_audio_path)
                print("✓ Cleaned up temporary audio file")
            except Exception as e:
                print(f"⚠ Warning: Could not delete temporary audio file: {e}")
        
        total_time = time.time() - start_time
        print(f"✓ Video created successfully in {total_time:.1f}s!")
        
        return True, "Video created successfully!"
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        # Cleanup on error
        temp_audio_path = os.path.join(os.path.dirname(OUTPUT_FILE_PATH), 'temp_mixed_audio.mp3')
        if os.path.exists(temp_audio_path):
            try:
                os.remove(temp_audio_path)
            except:
                pass
        return False, str(e)


def generate_video_preview(image_folder, audio_paths, output_path, intro_text, outro_text, config=None):
    """
    Generate a LOW-QUALITY preview video for real-time preview.
    Minimal processing for fast generation.
    
    Args:
        image_folder: Path to folder containing images
        audio_paths: List of paths to audio files
        output_path: Path where preview video will be saved
        intro_text: Opening title text
        outro_text: Closing title text
        config: Dictionary with configuration parameters
    
    Returns:
        (success: bool, message: str)
    """
    try:
        print("🎬 Generating PREVIEW video (low quality, fast render)...")
        
        # Ultra-low resolution for preview
        preview_width = 480
        preview_height = 270
        preview_fps = 12  # Low FPS for fast processing
        
        # Use configuration or defaults
        if config is None:
            config = {}
        
        # Get timing from config
        use_transitions = config.get('use_transitions', False)
        transition_duration = float(config.get('transition_duration', 1.0)) if use_transitions else 0
        transition_type = config.get('transition_type', 'crossfadein')
        
        # Image duration from config
        image_duration_setting = config.get('image_duration', 'auto')
        if image_duration_setting == 'auto':
            min_duration = float(config.get('min_image_duration', 2.0))
            max_duration = float(config.get('max_image_duration', 5.0))
            image_duration = (min_duration + max_duration) / 2  # Use average for preview
        else:
            image_duration = float(image_duration_setting)
        
        # For preview, keep it short but respect relative timing
        image_duration = min(image_duration, 3.0)  # Cap at 3 seconds for preview
        
        # Effects from config
        zoom_effect = config.get('zoom_effect', False)
        zoom_intensity = float(config.get('zoom_intensity', 0.1))
        
        # Get images
        image_files = []
        for ext in SUPPORTED_EXTENSIONS:
            image_files.extend(sorted(Path(image_folder).glob(f'*{ext}')))
            image_files.extend(sorted(Path(image_folder).glob(f'*{ext.upper()}')))
        
        image_files = sorted(set(str(f) for f in image_files))
        
        if not image_files:
            return False, "No images found"
        
        # Limit to first 5 images for preview
        image_files = image_files[:5]
        
        print(f"📸 Using {len(image_files)} images for preview")
        print(f"⚙️ Config: transitions={use_transitions}, duration={image_duration:.1f}s, zoom={zoom_effect}")
        
        # Create clips with configuration
        clips = []
        
        for img_path in image_files:
            try:
                # Read and resize immediately for memory efficiency
                img = Image.open(img_path)
                
                # Convert to RGB if needed (important for HEIC and other formats)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                img.thumbnail((preview_width, preview_height), Image.Resampling.LANCZOS)
                
                # Create clip with configured duration
                clip = ImageClip(np.array(img)).set_duration(image_duration)
                clip = clip.resize((preview_width, preview_height))
                
                # Apply zoom effect if enabled (simplified for preview)
                if zoom_effect:
                    # Simple zoom in effect
                    def zoom_in(t):
                        scale = 1 + (zoom_intensity * t / image_duration)
                        return scale
                    clip = clip.resize(lambda t: zoom_in(t))
                
                clips.append(clip)
            except Exception as e:
                print(f"⚠️ Skipping image {img_path}: {e}")
                continue
        
        if not clips:
            return False, "Could not load any images"
        
        # Concatenate with or without transitions
        if use_transitions and len(clips) > 1:
            print(f"🔄 Adding {transition_type} transitions ({transition_duration}s)")
            # Apply transitions between clips
            for i in range(len(clips) - 1):
                clips[i] = clips[i].crossfadeout(transition_duration)
            video = concatenate_videoclips(clips, method="compose", padding=-transition_duration)
        else:
            # No transitions - simple concatenation
            video = concatenate_videoclips(clips, method="chain")
        
        # Handle audio
        if audio_paths:
            try:
                # Load only first audio file for preview
                audio = AudioFileClip(audio_paths[0])
                
                # Trim audio to match video duration
                if audio.duration > video.duration:
                    audio = audio.set_duration(video.duration)
                else:
                    # Loop audio if needed
                    video = video.set_duration(audio.duration)
                
                video = video.set_audio(audio)
            except Exception as e:
                print(f"⚠️ Could not add audio: {e}")
        
        # Set to low FPS
        video = video.speedx(1.0).set_fps(preview_fps)
        
        # Write with minimal encoding
        print("💾 Writing preview video (this is fast)...")
        video.write_videofile(
            output_path,
            codec='libx264',
            audio_codec='aac',
            fps=preview_fps,
            verbose=False,
            logger=None,
            bitrate="500k"  # Very low bitrate
        )
        
        print("✅ Preview video created successfully")
        return True, "Preview created"
        
    except Exception as e:
        print(f"❌ Error creating preview: {e}")
        import traceback
        traceback.print_exc()
        return False, f"Preview error: {str(e)}"


