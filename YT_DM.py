import os
import re
import time
import platform
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk
import yt_dlp

# --- App Configuration & Styling ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class IDMProDownloader(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("YouTube IDM Pro - Advanced Control Edition")
        self.geometry("1100x650")
        self.resizable(False, False)

        # Core State Tracking
        self.active_threads = {}  # {item_id: {'cancel_flag': False, 'pause_flag': False}}
        self.current_merge_window = None

        self.setup_styles()
        self.create_menu_bar()
        self.create_toolbar()
        self.create_main_layout()

    def setup_styles(self):
        self.style = ttk.Style(self)
        self.style.theme_use("default")
        
        bg_color = "#2b2b2b"
        fg_color = "white"
        header_bg = "#3b3b3b"
        selected_bg = "#1f538d"

        self.style.configure("Treeview", 
                             background=bg_color, 
                             foreground=fg_color, 
                             fieldbackground=bg_color, 
                             rowheight=28, 
                             borderwidth=0)
        self.style.map("Treeview", background=[('selected', selected_bg)])
        self.style.configure("Treeview.Heading", 
                             background=header_bg, 
                             foreground=fg_color, 
                             relief="flat", 
                             font=("Segoe UI", 10, "bold"))

    def create_menu_bar(self):
        menu_bar = tk.Menu(self)
        self.config(menu=menu_bar)
        for m in ["Tasks", "File", "Downloads", "View", "Help"]:
            d_menu = tk.Menu(menu_bar, tearoff=0)
            d_menu.add_command(label="Options")
            menu_bar.add_cascade(label=m, menu=d_menu)

    def create_toolbar(self):
        toolbar_frame = ctk.CTkFrame(self, height=75, corner_radius=0, fg_color="#1f1f1f")
        toolbar_frame.pack(side="top", fill="x")

        buttons_data = [
            ("➕", "Add URL", self.open_add_dialog),
            ("⏸", "Pause Selected", self.pause_selected_item),
            ("▶", "Resume Selected", self.resume_selected_item),
            ("⏹", "Stop Selected", self.stop_selected_item),
            ("🗑", "Delete Selected", self.delete_selected_items),
            ("📁", "Open Folder", self.open_download_folder),
        ]

        for icon, text, command in buttons_data:
            btn_frame = ctk.CTkFrame(toolbar_frame, fg_color="transparent")
            btn_frame.pack(side="left", padx=8, pady=8)
            
            ctk.CTkButton(btn_frame, text=icon, width=40, height=38, font=("Segoe UI", 18), 
                          fg_color="#333333", hover_color="#444444", command=command).pack()
            ctk.CTkLabel(btn_frame, text=text, font=("Segoe UI", 11)).pack()

        # Auto-Stop / Shutdown on completion checkbox in Toolbar
        self.autostop_var = ctk.IntVar(value=0)
        autostop_chk = ctk.CTkCheckBox(toolbar_frame, text="Auto-close / Stop when queue finishes", variable=self.autostop_var, font=("Segoe UI", 11))
        autostop_chk.pack(side="right", padx=20, pady=20)

    def create_main_layout(self):
        paned_window = tk.PanedWindow(self, orient=tk.HORIZONTAL, bd=0, sashwidth=4, bg="#555555")
        paned_window.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # --- Sidebar Categories ---
        sidebar_frame = ctk.CTkFrame(paned_window, width=200, corner_radius=0)
        paned_window.add(sidebar_frame, minsize=160)
        
        ctk.CTkLabel(sidebar_frame, text="Categories", font=("Segoe UI", 13, "bold")).pack(fill="x", padx=10, pady=8)
        self.tree_categories = ttk.Treeview(sidebar_frame, show="tree")
        self.tree_categories.pack(fill="both", expand=True)

        cat_root = self.tree_categories.insert("", "end", text="All Downloads", open=True)
        self.tree_categories.insert(cat_root, "end", text="Videos (MP4)")
        self.tree_categories.insert(cat_root, "end", text="Music (MP3)")
        self.tree_categories.insert(cat_root, "end", text="Playlists")
        self.tree_categories.insert("", "end", text="Completed")

        # --- Main Downloads Grid (Supports Multi-Selection) ---
        grid_frame = ctk.CTkFrame(paned_window, corner_radius=0)
        paned_window.add(grid_frame, minsize=680)

        columns = ("name", "size", "status", "eta", "speed", "type")
        # selectmode='extended' enables multi-row selection with Ctrl/Shift
        self.tree_grid = ttk.Treeview(grid_frame, columns=columns, show="headings", selectmode="extended")
        
        self.tree_grid.heading("name", text="File Name", anchor="w")
        self.tree_grid.heading("size", text="Size", anchor="center")
        self.tree_grid.heading("status", text="Progress / Status", anchor="w")
        self.tree_grid.heading("eta", text="Time Left", anchor="center")
        self.tree_grid.heading("speed", text="Speed", anchor="center")
        self.tree_grid.heading("type", text="Format", anchor="center")

        self.tree_grid.column("name", width=340, anchor="w")
        self.tree_grid.column("size", width=85, anchor="center")
        self.tree_grid.column("status", width=220, anchor="w")
        self.tree_grid.column("eta", width=75, anchor="center")
        self.tree_grid.column("speed", width=85, anchor="center")
        self.tree_grid.column("type", width=70, anchor="center")

        self.tree_grid.pack(fill="both", expand=True)

    def open_add_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Advanced Download Options")
        dialog.geometry("480x420")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="YouTube URL (Video or Playlist):", font=("Segoe UI", 13, "bold")).pack(pady=(15, 5))
        url_entry = ctk.CTkEntry(dialog, width=420, height=38)
        url_entry.pack(pady=5)
        
        try:
            url_entry.insert(0, self.clipboard_get())
        except:
            pass

        opt_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        opt_frame.pack(pady=10, fill="x", padx=30)

        format_var = ctk.StringVar(value="Best Quality Video (MP4)")
        format_menu = ctk.CTkOptionMenu(opt_frame, variable=format_var, values=[
            "Best Quality Video (MP4)",
            "1080p Video (MP4)",
            "720p Video (MP4)",
            "Audio Only (MP3 - High Quality)"
        ], width=400, height=36)
        format_menu.pack(pady=5)

        playlist_chk = ctk.CTkCheckBox(dialog, text="Download Full Playlist (Parallel Multi-threaded)", font=("Segoe UI", 12))
        playlist_chk.pack(anchor="w", padx=40, pady=5)
        playlist_chk.select()

        thumb_chk = ctk.CTkCheckBox(dialog, text="Download Video Thumbnail (.jpg)", font=("Segoe UI", 12))
        thumb_chk.pack(anchor="w", padx=40, pady=5)
        thumb_chk.select()

        def start_tasks():
            url = url_entry.get().strip()
            if url:
                is_playlist = playlist_chk.get() == 1
                get_thumb = thumb_chk.get() == 1
                fmt = format_var.get()
                
                threading.Thread(target=self.prepare_downloads, args=(url, fmt, is_playlist, get_thumb), daemon=True).start()
                dialog.destroy()

        ctk.CTkButton(dialog, text="Start Downloading", command=start_tasks, width=200, height=42, 
                      fg_color="#E62117", hover_color="#B3120A", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=15)

    def open_download_folder(self):
        folder = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(folder, exist_ok=True)
        if platform.system() == "Windows":
            os.startfile(folder)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    # --- Multi-Delete Control ---
    def delete_selected_items(self):
        """حذف متعدد: يمسح كل العناصر المحددة في الجدول دفعة واحدة"""
        selected_items = self.tree_grid.selection()
        if not selected_items:
            messagebox.showwarning("Warning", "Please select one or more items to delete.")
            return

        for item_id in selected_items:
            if item_id in self.active_threads:
                self.active_threads[item_id]['cancel_flag'] = True # إيقاف الملف لو كان شغال
                del self.active_threads[item_id]
            self.tree_grid.delete(item_id)

    # --- Pause / Resume / Stop Controls per Item ---
    def pause_selected_item(self):
        for item_id in self.tree_grid.selection():
            if item_id in self.active_threads:
                self.active_threads[item_id]['pause_flag'] = True
                self.tree_grid.set(item_id, "status", "Paused ⏸")

    def resume_selected_item(self):
        for item_id in self.tree_grid.selection():
            if item_id in self.active_threads:
                self.active_threads[item_id]['pause_flag'] = False
                self.tree_grid.set(item_id, "status", "Resuming...")

    def stop_selected_item(self):
        for item_id in self.tree_grid.selection():
            if item_id in self.active_threads:
                self.active_threads[item_id]['cancel_flag'] = True
                self.tree_grid.set(item_id, "status", "Cancelled ✖")

    def prepare_downloads(self, url, format_choice, is_playlist, get_thumb):
        ydl_opts = {'extract_flat': 'in_playlist', 'quiet': True}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                meta = yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=False)

            if not meta:
                return

            entries = []
            if 'entries' in meta and is_playlist:
                for e in meta['entries']:
                    if e and 'url' in e:
                        entries.append(e['url'])
                    elif e and 'id' in e:
                        entries.append(f"https://www.youtube.com/watch?v={e['id']}")
            else:
                entries.append(url)

            if not entries and 'webpage_url' in meta:
                entries.append(meta['webpage_url'])
            elif not entries:
                entries.append(url)

            for target_url in entries:
                item_id = self.tree_grid.insert("", "end", values=("Initializing...", "--", "Queued...", "--", "--", "MP3" if "MP3" in format_choice else "MP4"))
                
                # تسجيل حالة كل ملف على حدة للتحكم فيه (إيقاف/استئناف/إلغاء)
                self.active_threads[item_id] = {'cancel_flag': False, 'pause_flag': False}
                
                threading.Thread(target=self.download_single_media, args=(target_url, format_choice, get_thumb, item_id), daemon=True).start()

        except Exception as e:
            print(f"Error preparing download: {e}")

    def download_single_media(self, url, format_choice, get_thumb, item_id):
        save_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        is_mp3 = "MP3" in format_choice
        thread_control = self.active_threads[item_id]

        def progress_hook(d):
            if thread_control['cancel_flag']:
                raise ValueError("Cancelled by user")

            while thread_control['pause_flag']:
                time.sleep(0.5)
                if thread_control['cancel_flag']:
                    raise ValueError("Cancelled by user")

            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes', 0)
                percent = int((downloaded / total) * 100) if total > 0 else 0
                
                size_str = f"{total / (1024*1024):.1f} MB" if total > 0 else "N/A"
                speed = d.get('_speed_str', 'N/A')
                eta = d.get('_eta_str', 'N/A')
                filename = os.path.basename(d.get('filename', 'Media'))

                progress_bar_str = f"[{'#' * (percent // 10)}{'.' * (10 - (percent // 10))}] {percent}%"

                self.after(0, lambda: self.tree_grid.item(item_id, values=(
                    filename, size_str, progress_bar_str, eta, speed, "MP3" if is_mp3 else "MP4"
                )))

            elif d['status'] == 'finished':
                self.after(0, lambda: self.show_merging_popup("Converting MP3 / Merging..." if is_mp3 else "Merging Video/Audio..."))
                self.after(0, lambda: self.tree_grid.item(item_id, values=(
                    os.path.basename(d.get('filename', 'Media')), "Processing...", "100%", "00:00", "0 B/s", "MP3" if is_mp3 else "MP4"
                )))

        ydl_opts = {
            'progress_hooks': [progress_hook],
            'outtmpl': os.path.join(save_dir, '%(title)s.%(ext)s'),
            'writethumbnail': get_thumb,
            'concurrent_fragment_downloads': 4,
            'ignoreerrors': True,
        }

        if is_mp3:
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'},
                    {'key': 'EmbedThumbnail'} if get_thumb else None
                ],
            })
            ydl_opts['postprocessors'] = [p for p in ydl_opts['postprocessors'] if p is not None]
        else:
            if "1080p" in format_choice:
                ydl_opts.update({'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best', 'merge_output_format': 'mp4'})
            elif "720p" in format_choice:
                ydl_opts.update({'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best', 'merge_output_format': 'mp4'})
            else:
                ydl_opts.update({'format': 'bestvideo+bestaudio/best', 'merge_output_format': 'mp4'})

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            self.after(0, lambda: self.close_merging_popup())
            self.after(0, lambda: self.tree_grid.set(item_id, "status", "Completed ✔"))

            # فحص خاصية الإيقاف التلقائي (Auto-Stop/Close) إذا انتهت كل الملفات
            if self.autostop_var.get() == 1:
                self.check_queue_completion(save_dir)

        except Exception as e:
            self.after(0, lambda: self.close_merging_popup())
            self.after(0, lambda: self.tree_grid.set(item_id, "status", "Cancelled / Error ✖"))

    def check_queue_completion(self, save_dir):
        """التحقق مما إذا كانت كل التحميلات انتهت لتنفيذ الإيقاف التلقائي"""
        all_items = self.tree_grid.get_children()
        all_done = True
        for item in all_items:
            status = self.tree_grid.set(item, "status")
            if "Completed" not in status and "Cancelled" not in status:
                all_done = False
                break
        
        if all_done:
            # إذا انتهت القائمة بالكامل، سؤال المستخدم أو إغلاق التطبيق تلقائياً
            def auto_action():
                answer = messagebox.askyesno("Queue Complete", "All downloads finished!\n\nWould you like to open the download folder and close the app?")
                if answer:
                    self.open_download_folder()
                    self.destroy()
            self.after(0, auto_action)

    def show_merging_popup(self, text_msg):
        if self.current_merge_window is not None and self.current_merge_window.winfo_exists():
            return
        
        self.current_merge_window = ctk.CTkToplevel(self)
        self.current_merge_window.title("Processing Media")
        self.current_merge_window.geometry("380x170")
        self.current_merge_window.resizable(False, False)
        self.current_merge_window.transient(self)
        self.current_merge_window.grab_set()

        ctk.CTkLabel(self.current_merge_window, text=f"⚙️ {text_msg}", font=("Segoe UI", 13, "bold"), text_color="#F1C40F").pack(pady=(20, 10))
        ctk.CTkLabel(self.current_merge_window, text="Please wait while processing the file...", font=("Segoe UI", 11), text_color="gray").pack(pady=(0, 15))
        
        p_bar = ctk.CTkProgressBar(self.current_merge_window, width=320, height=12, mode="indeterminate")
        p_bar.pack(pady=5)
        p_bar.start()

    def close_merging_popup(self):
        if self.current_merge_window is not None and self.current_merge_window.winfo_exists():
            self.current_merge_window.destroy()
            self.current_merge_window = None


if __name__ == "__main__":
    app = IDMProDownloader()
    app.mainloop()