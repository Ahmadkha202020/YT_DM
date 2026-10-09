import os
import re
import threading
import customtkinter as ctk
import yt_dlp

# --- App Configuration ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

app = ctk.CTk()
app.geometry("620x460")
app.title("YouTube Downloader Pro")
app.resizable(False, False)

selected_url = ""
is_playlist = False

# --- Helper Functions ---

def progress_hook(d):
    """Updates the progress bar, percentage, speed, and ETA in real time."""
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        downloaded = d.get('downloaded_bytes', 0)
        
        progress = (downloaded / total) if total > 0 else 0
        speed = d.get('_speed_str', 'N/A')
        eta = d.get('_eta_str', 'N/A')
        percent = d.get('_percent_str', f"{int(progress * 100)}%")
        
        # Track playlist progress if downloading a list
        playlist_prefix = ""
        info = d.get('info_dict', {})
        p_index = info.get('playlist_index')
        p_count = info.get('playlist_count') or info.get('n_entries')
        if p_index and p_count:
            playlist_prefix = f"[{p_index}/{p_count}] "

        def update_ui():
            progress_bar.set(progress)
            status_label.configure(
                text=f"{playlist_prefix}Downloading: {percent} | Speed: {speed} | ETA: {eta}",
                text_color="#3B8ED0"
            )

        app.after(0, update_ui)

    elif d['status'] == 'finished':
        def update_processing():
            progress_bar.set(1.0)
            status_label.configure(text="Processing & Merging media...", text_color="#F1C40F")
        app.after(0, update_processing)


def detect_quality_async():
    """Fetches video/playlist metadata in a background thread."""
    url = url_entry.get().strip()
    if not url:
        return
    
    status_label.configure(text="Detecting qualities from YouTube...", text_color="white")
    progress_bar.set(0)
    threading.Thread(target=process_detect_quality, args=(url,), daemon=True).start()


def process_detect_quality(url):
    global is_playlist
    ydl_opts = {'extract_flat': 'in_playlist', 'quiet': True}
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            meta = ydl.extract_info(url, download=False)

        if not meta:
            raise Exception("Unable to extract info")

        # Detect Playlist vs Single Video
        if 'entries' in meta:
            is_playlist = True
            title = meta.get('title', 'YouTube Playlist')
            count = len(list(meta['entries']))
            title_text = f"Playlist: {title[:40]}... ({count} videos)"
            options = [
                "Best Available Video (MP4)",
                "1080p Video (MP4)",
                "720p Video (MP4)",
                "Audio Only (MP3)"
            ]
        else:
            is_playlist = False
            title = meta.get('title', 'YouTube Video')
            title_text = f"Video: {title[:50]}"
            
            # Extract and sort unique resolutions
            formats = meta.get('formats', [])
            resolutions = set()
            for f in formats:
                h = f.get('height')
                if h and f.get('vcodec') != 'none':
                    resolutions.add(h)
            
            sorted_res = sorted(list(resolutions), reverse=True)
            options = [f"{h}p (MP4)" for h in sorted_res] if sorted_res else ["Best Quality (MP4)"]
            options.append("Audio Only (MP3)")

        def update_dropdown():
            info_label.configure(text=title_text)
            quality_dropdown.configure(values=options)
            quality_dropdown.set(options[0])
            status_label.configure(text="Ready to download", text_color="#2ECC71")

        app.after(0, update_dropdown)

    except Exception as e:
        def update_error():
            info_label.configure(text="No media loaded")
            status_label.configure(text="Failed to detect qualities. Check link.", text_color="#E74C3C")
        app.after(0, update_error)


def check_clipboard(event=None):
    """Automatically grabs YouTube URLs when you switch back to this app."""
    try:
        clipboard_content = app.clipboard_get().strip()
        current_text = url_entry.get().strip()
        
        # Verify valid YouTube domain and ensure it's not already pasted
        is_yt = ("youtube.com/" in clipboard_content or "youtu.be/" in clipboard_content)
        if is_yt and clipboard_content != current_text:
            url_entry.delete(0, "end")
            url_entry.insert(0, clipboard_content)
            detect_quality_async()
    except Exception:
        pass


def start_download():
    url = url_entry.get().strip()
    quality = quality_dropdown.get()
    
    if not url:
        status_label.configure(text="Please paste a URL first!", text_color="#E74C3C")
        return

    download_btn.configure(state="disabled")
    progress_bar.set(0)
    threading.Thread(target=process_download, args=(url, quality), daemon=True).start()


def process_download(url, quality):
    # Output structure: saves playlists in their own subfolders
    outtmpl = '%(playlist_title)s/%(playlist_index)s - %(title)s.%(ext)s' if is_playlist else '%(title)s.%(ext)s'

    ydl_opts = {
        'progress_hooks': [progress_hook],
        'outtmpl': outtmpl,
    }

    if "Audio Only" in quality:
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        # Match resolution height like '1080p', '720p', or fallback to best
        height_match = re.search(r'(\d+)p', quality)
        if height_match:
            h = height_match.group(1)
            ydl_opts.update({
                'format': f'bestvideo[height<={h}]+bestaudio/best[height<={h}]/best',
                'merge_output_format': 'mp4'
            })
        else:
            ydl_opts.update({
                'format': 'bestvideo+bestaudio/best',
                'merge_output_format': 'mp4'
            })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        def on_success():
            progress_bar.set(1.0)
            status_label.configure(text="Download Finished Successfully!", text_color="#2ECC71")
            download_btn.configure(state="normal")
        app.after(0, on_success)

    except Exception as e:
        def on_fail(err_msg=str(e)):
            status_label.configure(text=f"Error: {err_msg[:60]}...", text_color="#E74C3C")
            download_btn.configure(state="normal")
        app.after(0, on_fail)


# --- UI Layout ---

# Title
title_lbl = ctk.CTkLabel(app, text="YouTube Downloader", font=ctk.CTkFont(size=20, weight="bold"))
title_lbl.pack(pady=(20, 10))

# URL Input Bar + Manual Detect
input_frame = ctk.CTkFrame(app, fg_color="transparent")
input_frame.pack(pady=10)

url_entry = ctk.CTkEntry(input_frame, placeholder_text="Copy link & focus app (Auto-Paste) or paste here", width=420)
url_entry.pack(side="left", padx=(0, 8))

detect_btn = ctk.CTkButton(input_frame, text="Detect", width=80, command=detect_quality_async)
detect_btn.pack(side="left")

# Video / Playlist Information
info_label = ctk.CTkLabel(app, text="No media loaded", font=ctk.CTkFont(size=12, slant="italic"), text_color="gray")
info_label.pack(pady=(0, 10))

# Quality / Format Dropdown
quality_dropdown = ctk.CTkOptionMenu(app, values=["Select Quality / Audio"], width=300)
quality_dropdown.pack(pady=10)

# Active Progress Bar
progress_bar = ctk.CTkProgressBar(app, width=500, height=14)
progress_bar.set(0)
progress_bar.pack(pady=(20, 8))

# Live Status (Percentage, Speed, ETA)
status_label = ctk.CTkLabel(app, text="Waiting for link...", font=ctk.CTkFont(size=12))
status_label.pack(pady=(0, 15))

# Start Download Button
download_btn = ctk.CTkButton(app, text="Start Download", command=start_download, width=300, height=40,
                             fg_color="#E62117", hover_color="#B3120A", font=ctk.CTkFont(size=14, weight="bold"))
download_btn.pack(pady=(5, 20))

# Bind clipboard auto-paste to window focus
app.bind("<FocusIn>", check_clipboard)

app.mainloop()