import customtkinter as ctk
import yt_dlp
import threading

def start_download():
    url = url_entry.get()
    choice = format_var.get()
    status_label.configure(text="Downloading... (Check console for progress)")
    
    # Run in a background thread so the app doesn't freeze
    threading.Thread(target=process_download, args=(url, choice)).start()

def process_download(url, choice):
    ydl_opts = {}
    
    # Audio Option
    if choice == "Audio Only (MP3)":
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': '%(playlist_title)s/%(title)s.%(ext)s', # Creates a folder if it's a playlist
        }
    # Video Option
    else: 
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'merge_output_format': 'mp4',
            'outtmpl': '%(playlist_title)s/%(title)s.%(ext)s',
        }
        
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        status_label.configure(text="Download Complete!", text_color="green")
    except Exception as e:
        status_label.configure(text=f"Error: {str(e)}", text_color="red")

# --- App Interface Setup ---
ctk.set_appearance_mode("dark")
app = ctk.CTk()
app.geometry("550x300")
app.title("Custom YouTube Downloader")

# Input Field
url_entry = ctk.CTkEntry(app, placeholder_text="Paste YouTube Video or Playlist URL here", width=450)
url_entry.pack(pady=30)

# Video vs Audio Toggle
format_var = ctk.StringVar(value="Video (Best Quality MP4)")
format_dropdown = ctk.CTkOptionMenu(app, variable=format_var, values=["Video (Best Quality MP4)", "Audio Only (MP3)"], width=250)
format_dropdown.pack(pady=10)

# Download Button
download_btn = ctk.CTkButton(app, text="Start Download", command=start_download, width=250, fg_color="#E62117", hover_color="#B3120A")
download_btn.pack(pady=20)

# Status Label
status_label = ctk.CTkLabel(app, text="")
status_label.pack(pady=10)

app.mainloop()