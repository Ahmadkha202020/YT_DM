import os
import re
import sys
import json
import time
import socket
import webbrowser
import urllib.parse
import urllib.request
import platform
import subprocess
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk
import yt_dlp

# استدعاء مكتبة الريجستري في ويندوز لتسجيل البروتوكول تلقائياً
if platform.system() == "Windows":
    import winreg

# محاولة استدعاء مكتبة الصور لعرض الصورة المصغرة للفيديو
try:
    from PIL import Image
    from io import BytesIO
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# --- App Configuration & Theme ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# تحديد مسار عمل البرنامج الأساسي حتى لو تم فتحه من المتصفح عبر البروتوكول
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
os.chdir(BASE_DIR)

HISTORY_FILE = os.path.join(BASE_DIR, "downloads_history.json")
DEV_CONFIG_FILE = os.path.join(BASE_DIR, "developer_profile.json")
EXTENSION_DIR = os.path.join(BASE_DIR, "Browser_Extension")
SINGLE_INSTANCE_PORT = 54329  # بورت داخلي لإرسال الرابط للبرنامج لو كان مفتوحاً بالفعل

# =====================================================================
# بيانات المطور الافتراضية (يمكنك تعديلها هنا أو من داخل نافذة About Me)
# =====================================================================
DEFAULT_DEVELOPER_PROFILE = {
    "name": "Software Developer",
    "role": "Python & Desktop Applications Engineer",
    "email": "developer@example.com",
    "phone": "+20 100 000 0000",
    "whatsapp": "+201000000000",
    "note": "Need custom features, bug fixes, or software improvements? Feel free to reach out anytime!"
}


# --- Formatting Helpers (Clean Numbers Without ANSI Codes) ---

def format_bytes(b):
    if not b or b <= 0:
        return "0.0 MB"
    mb = b / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.1f} MB"


def format_speed(bps):
    if not bps or bps <= 0:
        return "0.0 MB/s"
    mbps = bps / (1024 * 1024)
    if mbps >= 1:
        return f"{mbps:.2f} MB/s"
    kbps = bps / 1024
    return f"{kbps:.0f} KB/s"


def format_time(seconds):
    if seconds is None or seconds < 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def parse_time_to_seconds(t_str):
    parts = [int(p) for p in t_str.strip().split(":") if p.isdigit()]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 1:
        return parts[0]
    return None


def extract_protocol_url(raw_arg):
    """استخراج رابط اليوتيوب النظيف من بروتوكول المتصفح ytidm://"""
    if not raw_arg:
        return ""
    arg = raw_arg.strip().strip('"').strip("'")
    if arg.startswith("ytidm://"):
        encoded = arg[len("ytidm://"):].rstrip("/")
        decoded = urllib.parse.unquote(encoded)
        return decoded
    elif arg.startswith("http"):
        return arg
    return ""


class IDMProUltimate(ctk.CTk):
    def __init__(self, startup_url=""):
        super().__init__()
        self.title("YouTube & Universal IDM Pro - Ultimate Edition")
        self.geometry("1180x680")
        self.minsize(1020, 600)

        # Core State & Settings
        self.default_download_path = os.path.join(os.path.expanduser("~"), "Downloads")
        self.output_path_var = ctk.StringVar(value=self.default_download_path)
        self.cookies_path = ""
        self.last_detected_url = ""
        self.current_category_filter = "All Downloads"

        # Load Developer Profile
        self.dev_profile = self.load_dev_profile()

        # Records Database: list of dicts persisted in JSON
        self.history_records = []
        # Active threads control: {item_id: {'cancel': False, 'pause': False, 'record': record}}
        self.active_tasks = {}

        # Popup References
        self.current_merge_window = None
        self.mini_widget_window = None

        self.setup_styles()
        self.create_menu_bar()
        self.create_toolbar()
        self.create_main_layout()
        self.create_context_menu()

        # Load saved JSON history
        self.load_history_from_json()

        # تشغيل مستمع البورت المحلي لاستقبال الروابط من المتصفح والبرنامج مفتوح
        self.start_ipc_listener()

        # Background Scheduler Loop
        self.after(3000, self.scheduler_tick)

        # Auto-paste clipboard monitor
        self.bind("<FocusIn>", self.check_clipboard)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # إذا تم تشغيل البرنامج عبر ضغطة زر من المتصفح، افتح نافذة التحميل فوراً بالرابط
        if startup_url:
            self.after(600, lambda: self.handle_incoming_browser_url(startup_url))

    # ==================== BROWSER EXTENSION & PROTOCOL INTEGRATION ====================

    def start_ipc_listener(self):
        """يستمع لأي رابط قادم من المتصفح إذا كان البرنامج مفتوحاً مسبقاً"""
        def listener():
            try:
                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
                server.listen(5)
                while True:
                    conn, _ = server.accept()
                    data = conn.recv(4096).decode("utf-8", errors="ignore").strip()
                    conn.close()
                    if data:
                        self.after(0, lambda u=data: self.handle_incoming_browser_url(u))
            except Exception as e:
                print(f"IPC Listener Notice: {e}")

        threading.Thread(target=listener, daemon=True).start()

    def handle_incoming_browser_url(self, video_url):
        """يرفع نافذة البرنامج للأمام ويفتح نافذة التحميل بالرابط القادم من يوتيوب"""
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))
        self.show_toast("Link Received from Browser 🌐", "Opening smart downloader...", "#2ECC71")
        self.open_add_dialog(initial_url=video_url)

    def generate_extension_files(self):
        """توليد ملفات الإضافة (manifest.json & content.js) تلقائياً في مجلد Browser_Extension"""
        os.makedirs(EXTENSION_DIR, exist_ok=True)

        manifest_data = {
            "manifest_version": 3,
            "name": "IDM Pro YouTube Downloader Bridge",
            "version": "1.0",
            "description": "Adds a direct 'Download with IDM Pro' button below YouTube videos.",
            "permissions": ["activeTab"],
            "content_scripts": [
                {
                    "matches": ["*://*.youtube.com/*"],
                    "js": ["content.js"],
                    "run_at": "document_idle"
                }
            ]
        }

        content_js_code = """function injectDownloadButton() {
    if (!window.location.href.includes("watch?v=") && !window.location.href.includes("shorts/")) return;
    if (document.getElementById("yt-idm-pro-btn")) return;

    const targetContainer = document.querySelector("#top-level-buttons-computed") || 
                            document.querySelector("#actions-inner #menu #top-level-buttons-computed") ||
                            document.querySelector("ytd-watch-metadata #actions");

    if (targetContainer) {
        const btn = document.createElement("button");
        btn.id = "yt-idm-pro-btn";
        btn.innerHTML = "⬇ Download (IDM Pro)";
        btn.style.cssText = `
            background-color: #E62117;
            color: #ffffff;
            border: none;
            border-radius: 18px;
            padding: 0 16px;
            height: 36px;
            margin-left: 8px;
            margin-right: 8px;
            font-family: 'Roboto', 'Segoe UI', Arial, sans-serif;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 2px 6px rgba(230, 33, 23, 0.4);
            transition: all 0.2s ease;
        `;

        btn.onmouseover = () => {
            btn.style.backgroundColor = "#B3120A";
            btn.style.transform = "scale(1.04)";
        };
        btn.onmouseout = () => {
            btn.style.backgroundColor = "#E62117";
            btn.style.transform = "scale(1)";
        };

        btn.onclick = () => {
            const currentUrl = window.location.href;
            window.location.href = "ytidm://" + encodeURIComponent(currentUrl);
        };

        targetContainer.prepend(btn);
    }
}

const observer = new MutationObserver(() => {
    injectDownloadButton();
});
observer.observe(document.body, { childList: true, subtree: true });
setInterval(injectDownloadButton, 2000);
"""

        with open(os.path.join(EXTENSION_DIR, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=4)

        with open(os.path.join(EXTENSION_DIR, "content.js"), "w", encoding="utf-8") as f:
            f.write(content_js_code)

    def register_custom_protocol_windows(self):
        """تسجيل البروتوكول ytidm:// في الـ Windows Registry ليربط المتصفح بالبرنامج مباشرة"""
        if platform.system() != "Windows":
            return False, "Custom Registry Protocol is only supported on Windows."

        try:
            # تحديد ما إذا كان البرنامج يعمل كملف بايثون (.py) أو ملف تنفيذي (.exe)
            if getattr(sys, 'frozen', False):
                launch_cmd = f'"{sys.executable}" "%1"'
            else:
                python_exe = sys.executable
                # يفضل استخدام pythonw.exe لعدم إظهار شاشة الكونسول السوداء عند الفتح من المتصفح
                pythonw_exe = python_exe.replace("python.exe", "pythonw.exe")
                if os.path.exists(pythonw_exe):
                    python_exe = pythonw_exe
                script_path = os.path.abspath(sys.argv[0])
                launch_cmd = f'"{python_exe}" "{script_path}" "%1"'

            key_path = r"Software\Classes\ytidm"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValue(key, "", winreg.REG_SZ, "URL:IDM Pro Downloader Protocol")
                winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

            cmd_key_path = r"Software\Classes\ytidm\shell\open\command"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_key_path) as cmd_key:
                winreg.SetValue(cmd_key, "", winreg.REG_SZ, launch_cmd)

            return True, launch_cmd
        except Exception as e:
            return False, str(e)

    def open_browser_extension_wizard(self):
        """تجهيز الإضافة وتسجيل الـ Registry وفتح نافذة الإرشادات السريعة للمستخدم"""
        self.generate_extension_files()
        reg_ok, reg_info = self.register_custom_protocol_windows()

        wiz = ctk.CTkToplevel(self)
        wiz.title("🧩 Install Browser Extension (1-Click Setup)")
        self.center_window(wiz, 600, 470)
        wiz.resizable(False, False)
        wiz.transient(self)
        wiz.grab_set()

        card = ctk.CTkFrame(wiz, corner_radius=12, fg_color="#1E1E1E", border_width=1, border_color="#9B59B6")
        card.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(card, text="🧩 YouTube Browser Extension Setup", font=("Segoe UI", 18, "bold"), text_color="#9B59B6").pack(pady=(15, 4))

        status_txt = "✅ Windows Registry Protocol (ytidm://) Registered Successfully!" if reg_ok else f"⚠ Protocol Notice: {reg_info}"
        status_clr = "#2ECC71" if reg_ok else "#F39C12"
        ctk.CTkLabel(card, text=status_txt, font=("Segoe UI", 12, "bold"), text_color=status_clr).pack(pady=2)

        ctk.CTkLabel(card, text="📁 Extension Folder Generated at:", font=("Segoe UI", 11, "bold"), text_color="gray").pack(pady=(8, 2))
        path_entry = ctk.CTkEntry(card, width=520, height=30, font=("Segoe UI", 11))
        path_entry.pack(pady=2)
        path_entry.insert(0, EXTENSION_DIR)
        path_entry.configure(state="readonly")

        steps_box = ctk.CTkTextbox(card, width=530, height=185, font=("Segoe UI", 12), corner_radius=8, fg_color="#292929")
        steps_box.pack(padx=20, pady=12)

        instructions = (
            "🚀 كيف تثبت الإضافة على متصفحك (Chrome / Edge / Brave) في 10 ثوانٍ:\n\n"
            "1️⃣ اضغط على زر (Open Extension Folder) بالأسفل ليفتح لك مجلد الإضافة.\n"
            "2️⃣ افتح المتصفح واكتب في شريط العنوان:  chrome://extensions\n"
            "   (أو في متصفح إيدج اكتب:  edge://extensions).\n"
            "3️⃣ فعّل زر وضع المطورين (Developer mode) الموجود أعلى يمين أو يسار الصفحة.\n"
            "4️⃣ اضغط على (Load unpacked / تحميل إضافة غير محزومة) واختر مجلد:\n"
            "   Browser_Extension  (أو اسحب المجلد بالماوس وأفلته داخل صفحة المتصفح!).\n\n"
            "🎉 مبروك! افتح أي فيديو يوتيوب الآن وستجد زر (⬇ Download IDM Pro) تحت الفيديو!"
        )
        steps_box.insert("1.0", instructions)
        steps_box.configure(state="disabled")

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(4, 12))

        def open_ext_folder():
            if platform.system() == "Windows":
                os.startfile(EXTENSION_DIR)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", EXTENSION_DIR])
            else:
                subprocess.Popen(["xdg-open", EXTENSION_DIR])

        def copy_ext_path():
            self.clipboard_clear()
            self.clipboard_append(EXTENSION_DIR)
            self.show_toast("Path Copied 📋", "Paste it inside Chrome Load Unpacked dialog!", "#9B59B6")

        ctk.CTkButton(btn_row, text="📂 Open Extension Folder", width=185, height=38, fg_color="#8E44AD", hover_color="#732D91", font=("Segoe UI", 12, "bold"), command=open_ext_folder).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="📋 Copy Folder Path", width=155, height=38, fg_color="#2980B9", font=("Segoe UI", 12, "bold"), command=copy_ext_path).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="Done", width=100, height=38, fg_color="#27AE60", font=("Segoe UI", 12, "bold"), command=wiz.destroy).pack(side="right", padx=5)

    # ==================== DEVELOPER PROFILE PERSISTENCE ====================

    def load_dev_profile(self):
        if os.path.exists(DEV_CONFIG_FILE):
            try:
                with open(DEV_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    merged = DEFAULT_DEVELOPER_PROFILE.copy()
                    merged.update(data)
                    return merged
            except Exception:
                pass
        return DEFAULT_DEVELOPER_PROFILE.copy()

    def save_dev_profile(self):
        try:
            with open(DEV_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.dev_profile, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Error saving developer profile: {e}")

    # ==================== WINDOW CENTRALIZATION & TOAST ====================

    def center_window(self, win, width, height):
        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - (width // 2)
        y = self.winfo_y() + (self.winfo_height() // 2) - (height // 2)
        win.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

    def show_toast(self, title, message, color="#2ECC71"):
        toast = ctk.CTkToplevel(self)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)

        w, h = 340, 85
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        toast.geometry(f"{w}x{h}+{screen_w - w - 25}+{screen_h - h - 65}")

        frame = ctk.CTkFrame(toast, corner_radius=10, fg_color="#1E1E1E", border_width=2, border_color=color)
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(frame, text=f"🔔 {title}", font=ctk.CTkFont(size=13, weight="bold"), text_color=color).pack(anchor="w", padx=12, pady=(8, 2))
        ctk.CTkLabel(frame, text=message[:55], font=ctk.CTkFont(size=11), text_color="white").pack(anchor="w", padx=12, pady=(0, 8))

        toast.after(4000, toast.destroy)

    # ==================== STYLES & MENU BAR ====================

    def setup_styles(self):
        self.style = ttk.Style(self)
        self.style.theme_use("default")

        bg_color = "#242424"
        fg_color = "white"
        header_bg = "#333333"
        selected_bg = "#1F538D"

        self.style.configure(
            "Treeview",
            background=bg_color,
            foreground=fg_color,
            fieldbackground=bg_color,
            rowheight=32,
            font=("Segoe UI", 10),
            borderwidth=0
        )
        self.style.map("Treeview", background=[('selected', selected_bg)])
        self.style.configure(
            "Treeview.Heading",
            background=header_bg,
            foreground=fg_color,
            relief="flat",
            font=("Segoe UI", 10, "bold")
        )

    def create_menu_bar(self):
        menu_bar = tk.Menu(self)
        self.config(menu=menu_bar)

        # 1. Tasks Menu
        tasks_menu = tk.Menu(menu_bar, tearoff=0)
        tasks_menu.add_command(label="➕ Add New Download URL...", command=lambda: self.open_add_dialog())
        tasks_menu.add_command(label="🧩 Install Browser Extension (YouTube Button)...", command=self.open_browser_extension_wizard)
        tasks_menu.add_separator()
        tasks_menu.add_command(label="📥 Import Batch URLs from TXT...", command=self.import_urls_from_txt)
        tasks_menu.add_command(label="🍪 Load cookies.txt (Private Videos)...", command=self.select_cookies_file)
        tasks_menu.add_separator()
        tasks_menu.add_command(label="🪟 Switch to Mini Floating Widget", command=self.open_mini_widget)
        tasks_menu.add_separator()
        tasks_menu.add_command(label="🚪 Exit Application", command=self.on_closing)
        menu_bar.add_cascade(label="Tasks", menu=tasks_menu)

        # 2. File Menu
        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="▶ Play / Open Selected File", command=self.play_selected_file)
        file_menu.add_command(label="📁 Show Selected File in Folder", command=self.open_selected_file_location)
        file_menu.add_command(label="📂 Open Default Output Folder", command=self.open_output_folder)
        file_menu.add_command(label="⚙️ Change Output Folder...", command=self.browse_folder)
        file_menu.add_separator()
        file_menu.add_command(label="💾 Export History to JSON...", command=self.export_json_history)
        file_menu.add_command(label="📂 Import History from JSON...", command=self.import_json_history)
        file_menu.add_separator()
        file_menu.add_command(label="🧹 Clear Completed List", command=self.clear_completed_entries)
        menu_bar.add_cascade(label="File", menu=file_menu)

        # 3. Downloads Menu
        dl_menu = tk.Menu(menu_bar, tearoff=0)
        dl_menu.add_command(label="▶ Resume Selected", command=self.resume_selected_items)
        dl_menu.add_command(label="⏸ Pause Selected", command=self.pause_selected_items)
        dl_menu.add_command(label="⏹ Cancel Selected", command=self.stop_selected_items)
        dl_menu.add_command(label="🔄 Re-Download Selected", command=self.redownload_selected_items)
        dl_menu.add_separator()
        dl_menu.add_command(label="⏸ Pause All Active", command=self.pause_all_items)
        dl_menu.add_command(label="▶ Resume All Paused", command=self.resume_all_items)
        dl_menu.add_command(label="⏹ Stop All Active", command=self.stop_all_items)
        menu_bar.add_cascade(label="Downloads", menu=dl_menu)

        # 4. View Menu
        view_menu = tk.Menu(menu_bar, tearoff=0)
        view_menu.add_command(label="🔄 Refresh Download Table", command=self.refresh_grid_view)
        view_menu.add_separator()
        view_menu.add_command(label="🌙 Dark Mode", command=lambda: ctk.set_appearance_mode("dark"))
        view_menu.add_command(label="☀️ Light Mode", command=lambda: ctk.set_appearance_mode("light"))
        view_menu.add_separator()
        view_menu.add_command(label="🪟 Show Mini Floating Widget", command=self.open_mini_widget)
        menu_bar.add_cascade(label="View", menu=view_menu)

        # 5. Help Menu
        help_menu = tk.Menu(menu_bar, tearoff=0)
        help_menu.add_command(label="👨‍💻 About Me (Contact Developer)", command=self.show_about_me_dialog)
        help_menu.add_command(label="🧩 Setup Browser Extension", command=self.open_browser_extension_wizard)
        help_menu.add_separator()
        help_menu.add_command(label="⚡ Auto-Update Engine (yt-dlp)", command=self.update_ytdlp_engine)
        help_menu.add_command(label="🎬 Check FFmpeg Status", command=self.check_ffmpeg_status)
        help_menu.add_separator()
        help_menu.add_command(label="ℹ️ About IDM Pro Ultimate", command=self.show_about_dialog)
        menu_bar.add_cascade(label="Help", menu=help_menu)

    # ==================== TOP TOOLBAR ====================

    def create_toolbar(self):
        toolbar = ctk.CTkFrame(self, height=78, corner_radius=0, fg_color="#1B1B1B")
        toolbar.pack(side="top", fill="x")

        buttons = [
            ("➕", "Add URL", lambda: self.open_add_dialog(), "#E62117"),
            ("▶", "Resume", self.resume_selected_items, "#27AE60"),
            ("⏸", "Pause", self.pause_selected_items, "#F39C12"),
            ("⏹", "Stop", self.stop_selected_items, "#C0392B"),
            ("🗑", "Delete", self.delete_selected_items, "#555555"),
            ("📁", "Folder", self.open_output_folder, "#2980B9"),
            ("🧩", "Browser Ext", self.open_browser_extension_wizard, "#9B59B6"),
            ("🪟", "Mini Widget", self.open_mini_widget, "#8E44AD"),
            ("👨‍💻", "About Me", self.show_about_me_dialog, "#16A085"),
        ]

        for icon, label, cmd, hover_clr in buttons:
            b_frame = ctk.CTkFrame(toolbar, fg_color="transparent")
            b_frame.pack(side="left", padx=5, pady=6)

            ctk.CTkButton(
                b_frame, text=icon, width=42, height=36, font=("Segoe UI", 17),
                fg_color="#2D2D2D", hover_color=hover_clr, command=cmd
            ).pack()
            ctk.CTkLabel(b_frame, text=label, font=("Segoe UI", 10, "bold")).pack(pady=(2, 0))

        # Right side controls: Speed Limiter, Connections, Auto-Stop
        right_panel = ctk.CTkFrame(toolbar, fg_color="transparent")
        right_panel.pack(side="right", padx=12, pady=6)

        top_opts = ctk.CTkFrame(right_panel, fg_color="transparent")
        top_opts.pack(fill="x", pady=2)

        ctk.CTkLabel(top_opts, text="🚀 Speed Limit:", font=("Segoe UI", 11, "bold")).pack(side="left", padx=4)
        self.speed_limit_var = ctk.StringVar(value="Unlimited")
        ctk.CTkOptionMenu(
            top_opts, variable=self.speed_limit_var,
            values=["Unlimited", "500 KB/s", "1 MB/s", "2 MB/s", "5 MB/s", "10 MB/s"],
            width=110, height=26, font=("Segoe UI", 11)
        ).pack(side="left", padx=4)

        ctk.CTkLabel(top_opts, text="🔗 Threads:", font=("Segoe UI", 11, "bold")).pack(side="left", padx=4)
        self.threads_var = ctk.StringVar(value="8 Threads")
        ctk.CTkOptionMenu(
            top_opts, variable=self.threads_var,
            values=["1 Thread", "4 Threads", "8 Threads", "16 Threads"],
            width=105, height=26, font=("Segoe UI", 11)
        ).pack(side="left", padx=4)

        bot_opts = ctk.CTkFrame(right_panel, fg_color="transparent")
        bot_opts.pack(fill="x", pady=(4, 0))

        self.autostop_var = ctk.IntVar(value=0)
        ctk.CTkCheckBox(
            bot_opts, text="Auto-Stop / Prompt when queue finishes",
            variable=self.autostop_var, font=("Segoe UI", 11), checkbox_width=18, checkbox_height=18
        ).pack(side="right", padx=4)

    # ==================== MAIN PANED LAYOUT ====================

    def create_main_layout(self):
        # Save Path Bar
        path_bar = ctk.CTkFrame(self, height=40, corner_radius=0, fg_color="#222222")
        path_bar.pack(fill="x", padx=0, pady=(0, 2))

        ctk.CTkLabel(path_bar, text="📁 Output Directory:", font=("Segoe UI", 12, "bold")).pack(side="left", padx=(15, 6), pady=6)
        ctk.CTkEntry(path_bar, textvariable=self.output_path_var, height=28, font=("Segoe UI", 11)).pack(side="left", fill="x", expand=True, padx=5, pady=6)
        ctk.CTkButton(path_bar, text="Browse...", width=85, height=28, command=self.browse_folder).pack(side="left", padx=4, pady=6)
        self.cookies_badge = ctk.CTkButton(
            path_bar, text="🍪 Cookies: Off", width=115, height=28,
            fg_color="#444444", hover_color="#555555", command=self.select_cookies_file
        )
        self.cookies_badge.pack(side="left", padx=(4, 15), pady=6)

        # Paned Window
        paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, bd=0, sashwidth=4, bg="#444444")
        paned.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Left Sidebar (Categories Filter)
        sidebar = ctk.CTkFrame(paned, width=200, corner_radius=8)
        paned.add(sidebar, minsize=175)

        ctk.CTkLabel(sidebar, text="📂 Categories Filter", font=("Segoe UI", 13, "bold")).pack(fill="x", padx=10, pady=8)
        self.tree_categories = ttk.Treeview(sidebar, show="tree", selectmode="browse")
        self.tree_categories.pack(fill="both", expand=True, padx=4, pady=4)

        root_cat = self.tree_categories.insert("", "end", iid="All Downloads", text="🌐 All Downloads", open=True)
        self.tree_categories.insert(root_cat, "end", iid="Videos (MP4)", text="🎬 Videos (MP4)")
        self.tree_categories.insert(root_cat, "end", iid="Music (MP3)", text="🎵 Music (MP3)")
        self.tree_categories.insert("", "end", iid="Completed", text="✅ Completed")
        self.tree_categories.insert("", "end", iid="Active / Queued", text="⏳ Active / Queued")
        self.tree_categories.insert("", "end", iid="Scheduled", text="⏰ Scheduled")
        self.tree_categories.insert("", "end", iid="Deleted / Cancelled", text="🗑 Deleted / Cancelled")

        self.tree_categories.bind("<<TreeviewSelect>>", self.on_category_selected)

        # Right Main Download Table
        grid_container = ctk.CTkFrame(paned, corner_radius=8)
        paned.add(grid_container, minsize=750)

        # Quick Selection Toolbar above Table
        sel_bar = ctk.CTkFrame(grid_container, height=36, fg_color="#1E1E1E", corner_radius=6)
        sel_bar.pack(fill="x", padx=6, pady=(6, 2))

        ctk.CTkLabel(sel_bar, text="☑️ Actions:", font=("Segoe UI", 11, "bold"), text_color="#3B8ED0").pack(side="left", padx=8)
        ctk.CTkButton(sel_bar, text="▶ Play File", width=85, height=24, font=("Segoe UI", 11, "bold"), fg_color="#27AE60", hover_color="#1E8449", command=self.play_selected_file).pack(side="left", padx=3, pady=4)
        ctk.CTkButton(sel_bar, text="📁 Show in Folder", width=110, height=24, font=("Segoe UI", 11), fg_color="#2980B9", command=self.open_selected_file_location).pack(side="left", padx=3, pady=4)
        ctk.CTkButton(sel_bar, text="Select All", width=75, height=24, font=("Segoe UI", 11), fg_color="#333333", command=self.select_all_rows).pack(side="left", padx=3, pady=4)
        ctk.CTkButton(sel_bar, text="Deselect", width=75, height=24, font=("Segoe UI", 11), fg_color="#333333", command=self.deselect_all_rows).pack(side="left", padx=3, pady=4)
        ctk.CTkButton(sel_bar, text="Mark Deleted", width=95, height=24, font=("Segoe UI", 11), fg_color="#7F8C8D", command=self.delete_selected_items).pack(side="left", padx=3, pady=4)
        ctk.CTkButton(sel_bar, text="Remove Permanently", width=130, height=24, font=("Segoe UI", 11), fg_color="#C0392B", command=self.permanently_remove_selected).pack(side="left", padx=3, pady=4)

        self.filter_status_lbl = ctk.CTkLabel(sel_bar, text="💡 Tip: Click '🧩 Browser Ext' to add YouTube Download Button!", font=("Segoe UI", 11), text_color="#F1C40F")
        self.filter_status_lbl.pack(side="right", padx=10)

        columns = ("select", "name", "size", "progress_bar", "status", "eta", "speed", "type", "date")
        self.tree_grid = ttk.Treeview(grid_container, columns=columns, show="headings", selectmode="extended")

        self.tree_grid.heading("select", text="☑", anchor="center")
        self.tree_grid.heading("name", text="File Name", anchor="w")
        self.tree_grid.heading("size", text="Size", anchor="center")
        self.tree_grid.heading("progress_bar", text="Visual Progress Bar", anchor="w")
        self.tree_grid.heading("status", text="State", anchor="center")
        self.tree_grid.heading("eta", text="Time Left", anchor="center")
        self.tree_grid.heading("speed", text="Speed", anchor="center")
        self.tree_grid.heading("type", text="Format", anchor="center")
        self.tree_grid.heading("date", text="Added / Scheduled", anchor="center")

        self.tree_grid.column("select", width=36, anchor="center")
        self.tree_grid.column("name", width=275, anchor="w")
        self.tree_grid.column("size", width=95, anchor="center")
        self.tree_grid.column("progress_bar", width=185, anchor="w")
        self.tree_grid.column("status", width=105, anchor="center")
        self.tree_grid.column("eta", width=75, anchor="center")
        self.tree_grid.column("speed", width=85, anchor="center")
        self.tree_grid.column("type", width=65, anchor="center")
        self.tree_grid.column("date", width=110, anchor="center")

        scrollbar = ttk.Scrollbar(grid_container, orient="vertical", command=self.tree_grid.yview)
        self.tree_grid.configure(yscrollcommand=scrollbar.set)
        self.tree_grid.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        scrollbar.pack(side="right", fill="y", padx=(0, 6), pady=6)

        self.tree_grid.bind("<<TreeviewSelect>>", self.on_grid_selection_change)
        self.tree_grid.bind("<Double-1>", lambda e: self.play_selected_file())
        self.tree_grid.bind("<Button-3>", self.show_context_menu)
        self.tree_grid.bind("<Button-2>", self.show_context_menu)

    # ==================== FULL RIGHT-CLICK CONTEXT MENU ====================

    def create_context_menu(self):
        self.context_menu = tk.Menu(
            self, tearoff=0, bg="#2B2B2B", fg="white",
            activebackground="#1F538D", activeforeground="white",
            font=("Segoe UI", 10)
        )
        self.context_menu.add_command(label="▶  Play / Open File (تشغيل الملف)", command=self.play_selected_file)
        self.context_menu.add_command(label="📁  Open File Location (فتح مكان الملف)", command=self.open_selected_file_location)
        self.context_menu.add_command(label="✏️  Rename File... (إعادة تسمية الملف)", command=self.rename_selected_file)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="▶  Resume Download (استئناف التحميل)", command=self.resume_selected_items)
        self.context_menu.add_command(label="⏸  Pause Download (إيقاف مؤقت)", command=self.pause_selected_items)
        self.context_menu.add_command(label="⏹  Stop / Cancel (إلغاء التحميل)", command=self.stop_selected_items)
        self.context_menu.add_command(label="🔄  Re-Download Again (إعادة التحميل من جديد)", command=self.redownload_selected_items)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🔗  Copy Source Video URL (نسخ رابط الفيديو)", command=self.copy_selected_url)
        self.context_menu.add_command(label="📋  Copy Local File Path (نسخ مسار الملف)", command=self.copy_selected_filepath)
        self.context_menu.add_command(label="ℹ️  File Properties & Details (تفاصيل الملف)", command=self.show_selected_properties)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🗑  Move to Deleted List (نقل إلى المحذوفات)", command=self.delete_selected_items)
        self.context_menu.add_command(label="❌  Delete File from Disk & List (حذف نهائي من الجهاز)", command=self.delete_from_disk_and_list)

    def show_context_menu(self, event):
        row_id = self.tree_grid.identify_row(event.y)
        if row_id:
            if row_id not in self.tree_grid.selection():
                self.tree_grid.selection_set(row_id)
                self.on_grid_selection_change()
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

    # ==================== FILE OPERATIONS FOR COMPLETED / SELECTED ITEMS ====================

    def get_selected_record(self):
        sel = self.tree_grid.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a file from the list first.")
            return None
        target_id = sel[0]
        for rec in self.history_records:
            if rec.get("id") == target_id:
                return rec
        return None

    def resolve_record_filepath(self, rec):
        if not rec:
            return None
        save_dir = rec.get("save_dir") or self.output_path_var.get().strip()
        stored_path = rec.get("filepath", "")
        if stored_path and os.path.exists(stored_path):
            return stored_path

        name = rec.get("name", "")
        candidate = os.path.join(save_dir, name)
        if name and os.path.exists(candidate):
            rec["filepath"] = candidate
            return candidate

        base_stem = os.path.splitext(name)[0]
        if base_stem and os.path.exists(save_dir):
            for ext in [".mp4", ".mp3", ".flac", ".wav", ".mkv", ".webm", ".m4a"]:
                test_p = os.path.join(save_dir, base_stem + ext)
                if os.path.exists(test_p):
                    rec["filepath"] = test_p
                    rec["name"] = os.path.basename(test_p)
                    return test_p

            clean_prefix = re.sub(r'[\\/*?:"<>|]', "", base_stem)[:25].lower()
            if clean_prefix:
                for fname in os.listdir(save_dir):
                    if fname.lower().startswith(clean_prefix) and not fname.endswith(".part"):
                        found_p = os.path.join(save_dir, fname)
                        rec["filepath"] = found_p
                        rec["name"] = fname
                        return found_p
        return None

    def play_selected_file(self):
        rec = self.get_selected_record()
        if not rec:
            return
        fpath = self.resolve_record_filepath(rec)
        if fpath and os.path.exists(fpath):
            try:
                if platform.system() == "Windows":
                    os.startfile(fpath)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", fpath])
                else:
                    subprocess.Popen(["xdg-open", fpath])
                self.show_toast("Playing Media ▶", os.path.basename(fpath), "#2ECC71")
            except Exception as e:
                messagebox.showerror("Error Opening File", str(e))
        else:
            messagebox.showwarning(
                "File Not Found on Disk",
                f"Could not find the file on disk:\n{rec.get('name')}\n\n"
                "It may still be downloading, moved, or deleted.\n"
                "You can right-click and choose 'Re-Download Again'."
            )

    def open_selected_file_location(self):
        rec = self.get_selected_record()
        if not rec:
            return
        fpath = self.resolve_record_filepath(rec)
        if fpath and os.path.exists(fpath):
            if platform.system() == "Windows":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(fpath)])
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-R", fpath])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(fpath)])
        else:
            self.open_output_folder()

    def rename_selected_file(self):
        rec = self.get_selected_record()
        if not rec:
            return
        fpath = self.resolve_record_filepath(rec)
        current_name = os.path.basename(fpath) if fpath else rec.get("name", "")

        dlg = ctk.CTkToplevel(self)
        dlg.title("Rename File")
        self.center_window(dlg, 440, 180)
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="✏️ Enter New File Name:", font=("Segoe UI", 13, "bold")).pack(pady=(18, 6))
        entry = ctk.CTkEntry(dlg, width=380, height=34, font=("Segoe UI", 12))
        entry.pack(pady=6)
        entry.insert(0, current_name)

        def save_rename():
            new_name = entry.get().strip()
            if not new_name:
                return
            if fpath and os.path.exists(fpath):
                 base_dir = os.path.dirname(fpath)
                 _, old_ext = os.path.splitext(fpath)
                 if not os.path.splitext(new_name)[1]:
                     new_name += old_ext
                 new_path = os.path.join(base_dir, new_name)
                 try:
                     os.rename(fpath, new_path)
                     rec["filepath"] = new_path
                     rec["name"] = new_name
                     self.show_toast("File Renamed ✏️", new_name, "#2ECC71")
                 except Exception as e:
                     messagebox.showerror("Rename Error", str(e))
                     return
            else:
                rec["name"] = new_name

            self.refresh_grid_view()
            self.save_history_to_json()
            dlg.destroy()

        ctk.CTkButton(dlg, text="Save New Name", width=160, height=36, fg_color="#27AE60", command=save_rename).pack(pady=12)

    def redownload_selected_items(self):
        sel = self.tree_grid.selection()
        if not sel:
            return
        for iid in sel:
            if iid in self.active_tasks:
                t = self.active_tasks[iid]
                t["cancel"] = False
                t["pause"] = False
                t["record"]["status"] = "Queued"
                t["record"]["progress_bar"] = self.build_visual_bar(0)
                threading.Thread(target=self.execute_single_download, args=(iid,), daemon=True).start()
        self.refresh_grid_view()

    def copy_selected_url(self):
        rec = self.get_selected_record()
        if rec and rec.get("url"):
            self.clipboard_clear()
            self.clipboard_append(rec["url"])
            self.show_toast("URL Copied 🔗", rec["url"], "#3B8ED0")

    def copy_selected_filepath(self):
        rec = self.get_selected_record()
        if not rec:
            return
        fpath = self.resolve_record_filepath(rec) or os.path.join(self.output_path_var.get(), rec.get("name", ""))
        self.clipboard_clear()
        self.clipboard_append(fpath)
        self.show_toast("File Path Copied 📋", fpath, "#3B8ED0")

    def show_selected_properties(self):
        rec = self.get_selected_record()
        if not rec:
            return
        fpath = self.resolve_record_filepath(rec) or "File not on disk yet"

        prop = ctk.CTkToplevel(self)
        prop.title("File Properties & Details")
        self.center_window(prop, 520, 320)
        prop.resizable(False, False)
        prop.transient(self)
        prop.grab_set()

        ctk.CTkLabel(prop, text="ℹ️ Download Item Details", font=("Segoe UI", 16, "bold"), text_color="#3B8ED0").pack(pady=(15, 10))

        info_box = ctk.CTkTextbox(prop, width=480, height=195, font=("Segoe UI", 12), corner_radius=8)
        info_box.pack(padx=20, pady=5)

        details_text = (
            f"• File Name: {rec.get('name')}\n\n"
            f"• Status: {rec.get('status')}\n"
            f"• Format / Type: {rec.get('type')}\n"
            f"• Size: {rec.get('size')}\n"
            f"• Date Added: {rec.get('date')}\n\n"
            f"• Local Path: {fpath}\n\n"
            f"• Source URL: {rec.get('url')}"
        )
        info_box.insert("1.0", details_text)
        info_box.configure(state="disabled")

        ctk.CTkButton(prop, text="Close", width=120, height=34, command=prop.destroy).pack(pady=10)

    def delete_from_disk_and_list(self):
        sel = list(self.tree_grid.selection())
        if not sel:
            return
        if not messagebox.askyesno("Confirm Permanent Disk Delete", f"Are you sure you want to permanently delete {len(sel)} file(s) from your computer hard drive and list?"):
            return

        for iid in sel:
            if iid in self.active_tasks:
                self.active_tasks[iid]["cancel"] = True
                rec = self.active_tasks[iid]["record"]
                fpath = self.resolve_record_filepath(rec)
                if fpath and os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass
                del self.active_tasks[iid]

        self.history_records = [r for r in self.history_records if r.get("id") not in set(sel)]
        self.refresh_grid_view()
        self.save_history_to_json()
        self.show_toast("Deleted from Disk ❌", f"Removed {len(sel)} file(s) permanently.", "#E74C3C")

    # ==================== HELP -> ABOUT ME (DEVELOPER CONTACT WINDOW) ====================

    def show_about_me_dialog(self):
        win = ctk.CTkToplevel(self)
        win.title("About Me - Contact Developer")
        self.center_window(win, 540, 440)
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        card = ctk.CTkFrame(win, corner_radius=14, fg_color="#1E1E1E", border_width=1, border_color="#3B8ED0")
        card.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(card, text="👨‍💻 Developer Contact & Support", font=("Segoe UI", 18, "bold"), text_color="#3B8ED0").pack(pady=(16, 4))

        name_lbl = ctk.CTkLabel(card, text=self.dev_profile["name"], font=("Segoe UI", 16, "bold"), text_color="white")
        name_lbl.pack(pady=2)

        role_lbl = ctk.CTkLabel(card, text=self.dev_profile["role"], font=("Segoe UI", 12), text_color="#2ECC71")
        role_lbl.pack(pady=(0, 8))

        note_lbl = ctk.CTkLabel(card, text=self.dev_profile["note"], font=("Segoe UI", 11), text_color="gray", wraplength=460, justify="center")
        note_lbl.pack(padx=20, pady=(0, 12))

        info_frame = ctk.CTkFrame(card, corner_radius=10, fg_color="#292929")
        info_frame.pack(fill="x", padx=20, pady=6)

        email_row = ctk.CTkFrame(info_frame, fg_color="transparent")
        email_row.pack(fill="x", padx=12, pady=(10, 5))

        email_lbl = ctk.CTkLabel(email_row, text=f"📧 Email:  {self.dev_profile['email']}", font=("Segoe UI", 12, "bold"), anchor="w")
        email_lbl.pack(side="left", fill="x", expand=True)

        def copy_email():
            self.clipboard_clear()
            self.clipboard_append(self.dev_profile["email"])
            self.show_toast("Email Copied 📋", self.dev_profile["email"], "#3B8ED0")

        def send_email():
            webbrowser.open(f"mailto:{self.dev_profile['email']}?subject=IDM%20Pro%20Feedback%20/%20Improvement")

        ctk.CTkButton(email_row, text="Send Email", width=85, height=28, fg_color="#2980B9", command=send_email).pack(side="right", padx=4)
        ctk.CTkButton(email_row, text="Copy", width=60, height=28, fg_color="#444444", command=copy_email).pack(side="right", padx=4)

        phone_row = ctk.CTkFrame(info_frame, fg_color="transparent")
        phone_row.pack(fill="x", padx=12, pady=(5, 10))

        phone_lbl = ctk.CTkLabel(phone_row, text=f"📱 Phone:  {self.dev_profile['phone']}", font=("Segoe UI", 12, "bold"), anchor="w")
        phone_lbl.pack(side="left", fill="x", expand=True)

        def copy_phone():
            self.clipboard_clear()
            self.clipboard_append(self.dev_profile["phone"])
            self.show_toast("Phone Number Copied 📋", self.dev_profile["phone"], "#2ECC71")

        def open_whatsapp():
            clean_num = re.sub(r"[^\d+]", "", self.dev_profile.get("whatsapp") or self.dev_profile["phone"]).lstrip("+")
            webbrowser.open(f"https://wa.me/{clean_num}")

        ctk.CTkButton(phone_row, text="WhatsApp", width=85, height=28, fg_color="#27AE60", hover_color="#1E8449", command=open_whatsapp).pack(side="right", padx=4)
        ctk.CTkButton(phone_row, text="Copy", width=60, height=28, fg_color="#444444", command=copy_phone).pack(side="right", padx=4)

        btn_bar = ctk.CTkFrame(card, fg_color="transparent")
        btn_bar.pack(fill="x", padx=20, pady=(16, 10))

        def open_edit_profile():
            edit_w = ctk.CTkToplevel(win)
            edit_w.title("Edit Developer Contact Info")
            self.center_window(edit_w, 460, 390)
            edit_w.resizable(False, False)
            edit_w.transient(win)
            edit_w.grab_set()

            ctk.CTkLabel(edit_w, text="✏️ Customize Your Developer Info", font=("Segoe UI", 14, "bold")).pack(pady=(12, 8))

            fields = {}
            for key, label_txt in [
                ("name", "Your Name:"),
                ("role", "Your Role / Title:"),
                ("email", "Your Email:"),
                ("phone", "Your Phone Number:"),
                ("whatsapp", "WhatsApp Number (with country code):"),
                ("note", "Message to Users:")
            ]:
                r = ctk.CTkFrame(edit_w, fg_color="transparent")
                r.pack(fill="x", padx=20, pady=4)
                ctk.CTkLabel(r, text=label_txt, width=140, anchor="w", font=("Segoe UI", 11)).pack(side="left")
                ent = ctk.CTkEntry(r, height=28, font=("Segoe UI", 11))
                ent.pack(side="left", fill="x", expand=True)
                ent.insert(0, self.dev_profile.get(key, ""))
                fields[key] = ent

            def save_changes():
                for k, ent_widget in fields.items():
                    self.dev_profile[k] = ent_widget.get().strip()
                self.save_dev_profile()
                name_lbl.configure(text=self.dev_profile["name"])
                role_lbl.configure(text=self.dev_profile["role"])
                note_lbl.configure(text=self.dev_profile["note"])
                email_lbl.configure(text=f"📧 Email:  {self.dev_profile['email']}")
                phone_lbl.configure(text=f"📱 Phone:  {self.dev_profile['phone']}")
                edit_w.destroy()
                self.show_toast("Developer Profile Saved ✔", "Your contact info has been updated!", "#2ECC71")

            ctk.CTkButton(edit_w, text="💾 Save My Info", width=180, height=36, fg_color="#27AE60", font=("Segoe UI", 12, "bold"), command=save_changes).pack(pady=14)

        ctk.CTkButton(btn_bar, text="✏️ Edit My Contact Info", width=170, height=34, fg_color="#333333", hover_color="#444444", command=open_edit_profile).pack(side="left")
        ctk.CTkButton(btn_bar, text="Close", width=110, height=34, fg_color="#E62117", hover_color="#B3120A", command=win.destroy).pack(side="right")

    # ==================== VISUAL BAR BUILDER ====================

    @staticmethod
    def build_visual_bar(percent):
        p = max(0.0, min(100.0, float(percent)))
        total_slots = 12
        filled = int(round((p / 100.0) * total_slots))
        empty = total_slots - filled
        bar_str = "▰" * filled + "▱" * empty
        return f"{bar_str}  {p:.1f}%"

    # ==================== ADD URL DIALOG ====================

    def open_add_dialog(self, initial_url=""):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Add New Download - Smart Scanner & Options")
        self.center_window(dialog, 660, 610)
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        subtitle_map = {"Arabic (ar)": "ar", "English (en)": "en"}

        top_f = ctk.CTkFrame(dialog, fg_color="transparent")
        top_f.pack(fill="x", padx=20, pady=(15, 6))

        url_entry = ctk.CTkEntry(top_f, placeholder_text="Paste YouTube, TikTok, Facebook, Instagram, or X link...", height=38, font=("Segoe UI", 12))
        url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        if initial_url:
            url_entry.insert(0, initial_url)
        else:
            try:
                clip = self.clipboard_get().strip()
                if clip.startswith("http"):
                    url_entry.insert(0, clip)
            except Exception:
                pass

        # Preview Card
        preview_card = ctk.CTkFrame(dialog, corner_radius=10, fg_color="#1E1E1E")
        preview_card.pack(fill="x", padx=20, pady=6)

        thumb_lbl = ctk.CTkLabel(
            preview_card, text="🖼\nThumbnail\nPreview", width=150, height=90,
            fg_color="#2B2B2B", corner_radius=8, font=("Segoe UI", 11), text_color="gray"
        )
        thumb_lbl.pack(side="left", padx=12, pady=10)

        meta_frame = ctk.CTkFrame(preview_card, fg_color="transparent")
        meta_frame.pack(side="left", fill="both", expand=True, padx=6, pady=10)

        title_preview_lbl = ctk.CTkLabel(meta_frame, text="Click 'Scan & Preview' to detect exact resolutions & thumbnail", font=("Segoe UI", 12, "bold"), anchor="w", wraplength=430)
        title_preview_lbl.pack(fill="x", pady=(2, 4))

        channel_preview_lbl = ctk.CTkLabel(meta_frame, text="Channel: --   |   Duration: --   |   Site: Universal", font=("Segoe UI", 11), text_color="gray", anchor="w")
        channel_preview_lbl.pack(fill="x")

        # Quality & Playlist Options
        q_frame = ctk.CTkFrame(dialog, corner_radius=10)
        q_frame.pack(fill="x", padx=20, pady=6)

        ctk.CTkLabel(q_frame, text="🎞 Quality / Format:", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, padx=12, pady=10, sticky="w")
        default_quals = [
            "1080p (Full HD) (MP4) ★ Max Quality",
            "720p (HD) (MP4)",
            "480p (MP4)",
            "360p (MP4)",
            "Audio Only (MP3 - 192kbps)",
            "Audio Only (FLAC - Lossless)",
            "Audio Only (WAV)"
        ]
        qual_dropdown = ctk.CTkOptionMenu(q_frame, values=default_quals, width=290, height=32)
        qual_dropdown.set(default_quals[0])
        qual_dropdown.grid(row=0, column=1, padx=6, pady=10, sticky="w")

        playlist_chk = ctk.CTkSwitch(q_frame, text="Download Full Playlist", font=("Segoe UI", 12, "bold"))
        if "list=" in url_entry.get():
            playlist_chk.select()
        playlist_chk.grid(row=0, column=2, padx=12, pady=10)

        # Subtitles & Thumbnail Saving
        sub_frame = ctk.CTkFrame(dialog, corner_radius=10)
        sub_frame.pack(fill="x", padx=20, pady=6)

        sub_chk = ctk.CTkCheckBox(sub_frame, text="💬 Download Subtitles (CC):", font=("Segoe UI", 12))
        sub_chk.grid(row=0, column=0, padx=12, pady=10, sticky="w")

        sub_dropdown = ctk.CTkOptionMenu(sub_frame, values=list(subtitle_map.keys()), width=190, height=30)
        sub_dropdown.grid(row=0, column=1, padx=6, pady=10, sticky="w")

        thumb_save_chk = ctk.CTkCheckBox(sub_frame, text="🖼 Save Cover Thumbnail (.jpg)", font=("Segoe UI", 12))
        thumb_save_chk.select()
        thumb_save_chk.grid(row=0, column=2, padx=12, pady=10, sticky="w")

        # Video Clip Trimmer
        trim_frame = ctk.CTkFrame(dialog, corner_radius=10)
        trim_frame.pack(fill="x", padx=20, pady=6)

        trim_chk = ctk.CTkCheckBox(trim_frame, text="✂️ Trim Video Clip (Part Only):", font=("Segoe UI", 12, "bold"))
        trim_chk.grid(row=0, column=0, padx=12, pady=10, sticky="w")

        ctk.CTkLabel(trim_frame, text="Start:", font=("Segoe UI", 11)).grid(row=0, column=1, padx=4)
        start_time_entry = ctk.CTkEntry(trim_frame, placeholder_text="00:00:30", width=90, height=28)
        start_time_entry.grid(row=0, column=2, padx=4)

        ctk.CTkLabel(trim_frame, text="End:", font=("Segoe UI", 11)).grid(row=0, column=3, padx=4)
        end_time_entry = ctk.CTkEntry(trim_frame, placeholder_text="00:02:00", width=90, height=28)
        end_time_entry.grid(row=0, column=4, padx=4)

        # Download Scheduler
        sched_frame = ctk.CTkFrame(dialog, corner_radius=10)
        sched_frame.pack(fill="x", padx=20, pady=6)

        sched_chk = ctk.CTkCheckBox(sched_frame, text="⏰ Schedule Start Time (24h HH:MM):", font=("Segoe UI", 12, "bold"))
        sched_chk.grid(row=0, column=0, padx=12, pady=10, sticky="w")

        sched_entry = ctk.CTkEntry(sched_frame, placeholder_text="02:30", width=100, height=28)
        sched_entry.grid(row=0, column=1, padx=8, pady=10, sticky="w")
        ctk.CTkLabel(sched_frame, text="(Starts automatically when clock matches)", font=("Segoe UI", 10), text_color="gray").grid(row=0, column=2, padx=6, sticky="w")

        def scan_link_inside_dialog():
            u = url_entry.get().strip()
            if not u:
                return
            title_preview_lbl.configure(text="Scanning video resolutions, thumbnail & subtitles...", text_color="#3B8ED0")

            def worker():
                opts = {'noplaylist': True, 'quiet': True, 'no_warnings': True}
                if self.cookies_path and os.path.exists(self.cookies_path):
                    opts['cookiefile'] = self.cookies_path
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        meta = ydl.extract_info(u, download=False)
                    if 'entries' in meta and meta['entries']:
                        meta = list(meta['entries'])[0]

                    t_title = meta.get('title', 'Media File')
                    t_up = meta.get('uploader', 'Unknown')
                    t_dur = format_time(meta.get('duration'))
                    t_site = meta.get('extractor_key', 'Web')
                    thumb_url = meta.get('thumbnail')

                    res_map = {}
                    for f in meta.get('formats', []):
                        h = f.get('height')
                        if h and f.get('vcodec', 'none') != 'none' and h >= 144:
                            sz = f.get('filesize') or f.get('filesize_approx') or 0
                            if h not in res_map or sz > res_map[h]:
                                res_map[h] = sz

                    s_heights = sorted(res_map.keys(), reverse=True)
                    q_list = []
                    for idx, h in enumerate(s_heights):
                        tag = " (4K)" if h >= 2160 else " (2K)" if h == 1440 else " (Full HD)" if h == 1080 else " (HD)" if h == 720 else ""
                        sz_s = f" ~{format_bytes(res_map[h])}" if res_map[h] > 0 else ""
                        mx = " ★ Max Quality" if idx == 0 else ""
                        q_list.append(f"{h}p{tag} (MP4){sz_s}{mx}")

                    if not q_list:
                        q_list = ["Best Available (MP4)"]
                    q_list.extend(["Audio Only (MP3 - 192kbps)", "Audio Only (FLAC - Lossless)", "Audio Only (WAV)"])

                    m_subs = meta.get('subtitles', {}) or {}
                    a_subs = meta.get('automatic_captions', {}) or {}
                    new_s_map = {}
                    for code, name in [('ar', 'Arabic'), ('en', 'English'), ('fr', 'French'), ('es', 'Spanish'), ('de', 'German')]:
                        if code in m_subs:
                            new_s_map[f"{name} ({code}) - Official"] = code
                        elif code in a_subs:
                            new_s_map[f"{name} ({code}) - Auto CC"] = code
                    if not new_s_map:
                        new_s_map = {"No Subtitles Available": "none"}

                    subtitle_map.clear()
                    subtitle_map.update(new_s_map)

                    ctk_img = None
                    if PIL_AVAILABLE and thumb_url:
                        try:
                            req = urllib.request.Request(thumb_url, headers={'User-Agent': 'Mozilla/5.0'})
                            raw_data = urllib.request.urlopen(req, timeout=4).read()
                            pil_img = Image.open(BytesIO(raw_data))
                            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(150, 88))
                        except Exception:
                            ctk_img = None

                    def apply_ui():
                        if not dialog.winfo_exists():
                            return
                        title_preview_lbl.configure(text=f"🎬 {t_title[:65]}", text_color="#2ECC71")
                        channel_preview_lbl.configure(text=f"📺 {t_up[:22]}   |   ⏱ {t_dur}   |   🌐 {t_site}")
                        qual_dropdown.configure(values=q_list)
                        qual_dropdown.set(q_list[0])
                        sub_dropdown.configure(values=list(subtitle_map.keys()))
                        sub_dropdown.set(list(subtitle_map.keys())[0])
                        if ctk_img:
                            thumb_lbl.configure(image=ctk_img, text="")

                    self.after(0, apply_ui)
                except Exception:
                    self.after(0, lambda: title_preview_lbl.configure(text="Ready to download (Direct stream mode)", text_color="#F39C12"))

            threading.Thread(target=worker, daemon=True).start()

        scan_btn = ctk.CTkButton(top_f, text="🔍 Scan & Preview", width=140, height=38, font=("Segoe UI", 12, "bold"), command=scan_link_inside_dialog)
        scan_btn.pack(side="right")

        if url_entry.get().strip():
            dialog.after(200, scan_link_inside_dialog)

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(12, 10))

        def confirm_start():
            target_url = url_entry.get().strip()
            if not target_url:
                return
            options = {
                "quality": qual_dropdown.get(),
                "is_playlist": playlist_chk.get() == 1,
                "download_subs": sub_chk.get() == 1,
                "sub_lang": subtitle_map.get(sub_dropdown.get(), "ar"),
                "save_thumb": thumb_save_chk.get() == 1,
                "trim_enabled": trim_chk.get() == 1,
                "trim_start": start_time_entry.get().strip(),
                "trim_end": end_time_entry.get().strip(),
                "schedule_enabled": sched_chk.get() == 1,
                "schedule_time": sched_entry.get().strip(),
            }
            dialog.destroy()
            threading.Thread(target=self.prepare_downloads, args=(target_url, options), daemon=True).start()

        ctk.CTkButton(
            btn_row, text="⬇ Start / Queue Download", width=240, height=42,
            fg_color="#E62117", hover_color="#B3120A", font=("Segoe UI", 14, "bold"), command=confirm_start
        ).pack(side="right", padx=6)

        ctk.CTkButton(
            btn_row, text="Cancel", width=110, height=42,
            fg_color="#444444", hover_color="#555555", command=dialog.destroy
        ).pack(side="right", padx=6)

    # ==================== DOWNLOAD PREPARATION & PARALLEL ENGINE ====================

    def prepare_downloads(self, url, options):
        ydl_opts = {'extract_flat': 'in_playlist', 'quiet': True, 'no_warnings': True}
        if self.cookies_path and os.path.exists(self.cookies_path):
            ydl_opts['cookiefile'] = self.cookies_path

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                meta = ydl.extract_info(url, download=False)
        except Exception:
            meta = None

        entries = []
        if meta and 'entries' in meta and options.get("is_playlist"):
            for e in meta['entries']:
                if e and e.get('url'):
                    entries.append((e.get('title', 'Playlist Video'), e['url']))
                elif e and e.get('id'):
                    entries.append((e.get('title', 'Playlist Video'), f"https://www.youtube.com/watch?v={e['id']}"))
        else:
            title_guess = meta.get('title', url) if meta else url
            entries.append((title_guess, url))

        qual_str = options.get("quality", "MP4")
        fmt_type = "MP3" if "MP3" in qual_str else "FLAC" if "FLAC" in qual_str else "WAV" if "WAV" in qual_str else "MP4"
        is_scheduled = options.get("schedule_enabled") and bool(options.get("schedule_time"))
        sched_time = options.get("schedule_time", "")
        save_dir = self.output_path_var.get().strip()

        for title_hint, item_url in entries:
            item_id = f"dl_{int(time.time() * 1000)}_{len(self.history_records)}"
            initial_state = "Scheduled" if is_scheduled else "Queued"
            date_str = f"⏰ {sched_time}" if is_scheduled else datetime.now().strftime("%Y-%m-%d %H:%M")

            record = {
                "id": item_id,
                "name": title_hint[:65],
                "url": item_url,
                "save_dir": save_dir,
                "filepath": "",
                "size": "--",
                "progress_bar": self.build_visual_bar(0),
                "status": initial_state,
                "eta": "--:--",
                "speed": "0.0 MB/s",
                "type": fmt_type,
                "date": date_str,
                "options": options
            }
            self.history_records.append(record)
            self.active_tasks[item_id] = {"cancel": False, "pause": False, "record": record}

            self.after(0, self.refresh_grid_view)
            self.save_history_to_json()

            if not is_scheduled:
                threading.Thread(target=self.execute_single_download, args=(item_id,), daemon=True).start()
            else:
                self.after(0, lambda t=sched_time: self.show_toast("Task Scheduled", f"Will start automatically at {t}", "#F39C12"))

    def execute_single_download(self, item_id):
        if item_id not in self.active_tasks:
            return
        task_info = self.active_tasks[item_id]
        record = task_info["record"]
        options = record.get("options", {})
        url = record["url"]
        save_dir = self.output_path_var.get().strip()
        record["save_dir"] = save_dir
        os.makedirs(save_dir, exist_ok=True)

        qual_str = options.get("quality", "MP4")
        is_audio = any(k in qual_str for k in ["MP3", "FLAC", "WAV"])
        target_ext = "mp3" if "MP3" in qual_str else "flac" if "FLAC" in qual_str else "wav" if "WAV" in qual_str else "mp4"

        def progress_hook(d):
            if task_info["cancel"]:
                raise ValueError("Download cancelled by user.")

            while task_info["pause"]:
                time.sleep(0.3)
                if task_info["cancel"]:
                    raise ValueError("Download cancelled by user.")

            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes', 0)
                speed_bps = d.get('speed') or 0
                eta_sec = d.get('eta')

                progress = (downloaded / total) if total > 0 else 0.0
                if progress > 1.0:
                    progress = 1.0
                pct = progress * 100.0

                raw_filename = d.get('filename', record["name"])
                fname = os.path.basename(raw_filename)
                size_str = f"{format_bytes(downloaded)} / {format_bytes(total)}" if total > 0 else format_bytes(downloaded)
                speed_str = format_speed(speed_bps)
                eta_str = format_time(eta_sec)
                vis_bar = self.build_visual_bar(pct)

                record["name"] = fname
                record["size"] = size_str
                record["progress_bar"] = vis_bar
                record["status"] = "Downloading"
                record["eta"] = eta_str
                record["speed"] = speed_str

                def update_ui():
                    if self.tree_grid.exists(item_id):
                        sel_mark = "☑️" if item_id in self.tree_grid.selection() else "⬜"
                        self.tree_grid.item(item_id, values=(
                            sel_mark, record["name"], record["size"], record["progress_bar"],
                            record["status"], record["eta"], record["speed"], record["type"], record["date"]
                        ))
                    self.update_mini_widget(pct, speed_str, fname)

                self.after(0, update_ui)

            elif d['status'] == 'finished':
                total_b = d.get('total_bytes') or d.get('downloaded_bytes') or 0
                mb_str = format_bytes(total_b)
                record["progress_bar"] = self.build_visual_bar(100)
                record["status"] = "Converting MP3..." if is_audio else "Merging..."
                record["eta"] = "00:00"
                record["speed"] = "Processing"

                def on_merge_start():
                    if self.tree_grid.exists(item_id):
                        self.tree_grid.set(item_id, "progress_bar", record["progress_bar"])
                        self.tree_grid.set(item_id, "status", record["status"])
                    self.show_merging_popup(record["name"], mb_str, is_audio)

                self.after(0, on_merge_start)

        threads_num = int(self.threads_var.get().split()[0])
        ydl_opts = {
            'progress_hooks': [progress_hook],
            'outtmpl': os.path.join(save_dir, '%(title)s.%(ext)s'),
            'noplaylist': True,
            'concurrent_fragment_downloads': threads_num,
            'ignoreerrors': False,
            'nocolor': True,
            'writethumbnail': options.get("save_thumb", False),
        }

        spd_choice = self.speed_limit_var.get()
        if spd_choice != "Unlimited":
            val_num = float(spd_choice.split()[0])
            if "KB" in spd_choice:
                ydl_opts['ratelimit'] = int(val_num * 1024)
            else:
                ydl_opts['ratelimit'] = int(val_num * 1024 * 1024)

        if self.cookies_path and os.path.exists(self.cookies_path):
            ydl_opts['cookiefile'] = self.cookies_path

        if options.get("download_subs") and options.get("sub_lang") != "none":
            ydl_opts.update({
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': [options.get("sub_lang", "ar")],
                'subtitlesformat': 'srt/vtt/best',
            })

        if options.get("trim_enabled"):
            s_sec = parse_time_to_seconds(options.get("trim_start", ""))
            e_sec = parse_time_to_seconds(options.get("trim_end", ""))
            if s_sec is not None and e_sec is not None and e_sec > s_sec:
                ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(None, [(s_sec, e_sec)])
                ydl_opts['force_keyframes_at_cuts'] = True

        postprocessors = []
        if is_audio:
            ydl_opts['format'] = 'bestaudio/best'
            postprocessors.append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': target_ext,
                'preferredquality': '192',
            })
            if options.get("save_thumb") and target_ext == "mp3":
                postprocessors.append({'key': 'EmbedThumbnail'})
            postprocessors.append({'key': 'FFmpegMetadata'})
        else:
            h_match = re.search(r'(\d+)p', qual_str)
            if h_match:
                h = h_match.group(1)
                ydl_opts['format'] = f'bestvideo[height<={h}]+bestaudio/best[height<={h}]/best'
            else:
                ydl_opts['format'] = 'bestvideo+bestaudio/best'
            ydl_opts['merge_output_format'] = 'mp4'

        if postprocessors:
            ydl_opts['postprocessors'] = postprocessors

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    prepared = ydl.prepare_filename(info)
                    final_file = os.path.splitext(prepared)[0] + f".{target_ext}"
                    record["filepath"] = final_file
                    record["name"] = os.path.basename(final_file)

            record["status"] = "Completed"
            record["progress_bar"] = self.build_visual_bar(100)
            record["eta"] = "00:00"
            record["speed"] = "Done"
            self.save_history_to_json()

            def on_complete():
                self.close_merging_popup()
                self.refresh_grid_view()
                self.show_toast("Download Complete ✔", record["name"], "#2ECC71")
                self.prompt_completion_popup(record)
                if self.autostop_var.get() == 1:
                    self.check_queue_auto_stop(save_dir)

            self.after(0, on_complete)

        except ValueError:
            record["status"] = "Cancelled"
            record["speed"] = "0.0 MB/s"
            self.save_history_to_json()
            self.after(0, self.close_merging_popup)
            self.after(0, self.refresh_grid_view)
        except Exception:
            record["status"] = "Error"
            record["speed"] = "Failed"
            self.save_history_to_json()
            self.after(0, self.close_merging_popup)
            self.after(0, self.refresh_grid_view)
            self.after(0, lambda: self.show_toast("Download Error ✖", f"Failed: {record['name']}", "#E74C3C"))

    # ==================== MERGING POPUP & COMPLETION MESSAGE ====================

    def show_merging_popup(self, filename, size_mb_str, is_audio):
        if self.current_merge_window is not None and self.current_merge_window.winfo_exists():
            return

        self.current_merge_window = ctk.CTkToplevel(self)
        self.current_merge_window.title("Processing & Merging Media")
        self.center_window(self.current_merge_window, 430, 210)
        self.current_merge_window.resizable(False, False)
        self.current_merge_window.transient(self)

        header_text = "🎵 Converting Audio Stream & Embedding Metadata..." if is_audio else "⚙️ Merging High-Resolution Video & Audio (FFmpeg)..."
        ctk.CTkLabel(self.current_merge_window, text=header_text, font=("Segoe UI", 13, "bold"), text_color="#F1C40F").pack(pady=(18, 6))
        ctk.CTkLabel(self.current_merge_window, text=f"File: {filename[:48]}", font=("Segoe UI", 11), text_color="white").pack(pady=2)
        ctk.CTkLabel(self.current_merge_window, text=f"Processed Stream Size: {size_mb_str}   |   Remaining: ~Few Seconds", font=("Segoe UI", 11, "bold"), text_color="#2ECC71").pack(pady=(2, 12))

        p_bar = ctk.CTkProgressBar(self.current_merge_window, width=360, height=14, corner_radius=7, mode="indeterminate", progress_color="#F1C40F")
        p_bar.pack(pady=8)
        p_bar.start()

    def close_merging_popup(self):
        if self.current_merge_window is not None and self.current_merge_window.winfo_exists():
            self.current_merge_window.destroy()
            self.current_merge_window = None

    def prompt_completion_popup(self, record):
        pop = ctk.CTkToplevel(self)
        pop.title("Download Finished ✔")
        self.center_window(pop, 460, 200)
        pop.resizable(False, False)
        pop.transient(self)
        pop.grab_set()

        ctk.CTkLabel(pop, text="✅ Download & Merging Completed!", font=("Segoe UI", 15, "bold"), text_color="#2ECC71").pack(pady=(18, 6))
        ctk.CTkLabel(pop, text=record.get("name", "")[:54], font=("Segoe UI", 11), text_color="white").pack(pady=(0, 18))

        btn_f = ctk.CTkFrame(pop, fg_color="transparent")
        btn_f.pack(pady=6)

        def play_now():
            pop.destroy()
            self.tree_grid.selection_set(record["id"])
            self.play_selected_file()

        def open_folder_now():
            pop.destroy()
            self.tree_grid.selection_set(record["id"])
            self.open_selected_file_location()

        ctk.CTkButton(btn_f, text="▶ Play File", width=125, height=38, fg_color="#27AE60", hover_color="#1E8449", font=("Segoe UI", 12, "bold"), command=play_now).pack(side="left", padx=6)
        ctk.CTkButton(btn_f, text="📁 Open Folder", width=135, height=38, fg_color="#2980B9", font=("Segoe UI", 12, "bold"), command=open_folder_now).pack(side="left", padx=6)
        ctk.CTkButton(btn_f, text="✖ Close", width=100, height=38, fg_color="#555555", hover_color="#444444", font=("Segoe UI", 12), command=pop.destroy).pack(side="left", padx=6)

    # ==================== MINI FLOATING WIDGET ====================

    def open_mini_widget(self):
        if self.mini_widget_window is not None and self.mini_widget_window.winfo_exists():
            self.mini_widget_window.lift()
            return

        self.mini_widget_window = ctk.CTkToplevel(self)
        self.mini_widget_window.title("IDM Mini Widget")
        self.mini_widget_window.geometry("320x125+50+50")
        self.mini_widget_window.resizable(False, False)
        self.mini_widget_window.attributes("-topmost", True)

        f = ctk.CTkFrame(self.mini_widget_window, corner_radius=10, fg_color="#181818")
        f.pack(fill="both", expand=True, padx=4, pady=4)

        self.mini_title_lbl = ctk.CTkLabel(f, text="🚀 Live Monitor (Always on Top)", font=("Segoe UI", 11, "bold"), text_color="#3B8ED0")
        self.mini_title_lbl.pack(anchor="w", padx=10, pady=(6, 2))

        self.mini_bar = ctk.CTkProgressBar(f, width=290, height=10, progress_color="#2ECC71")
        self.mini_bar.set(0)
        self.mini_bar.pack(padx=10, pady=4)

        bottom_row = ctk.CTkFrame(f, fg_color="transparent")
        bottom_row.pack(fill="x", padx=10, pady=4)

        self.mini_stats_lbl = ctk.CTkLabel(bottom_row, text="0.0%  |  0.0 MB/s", font=("Segoe UI", 11, "bold"))
        self.mini_stats_lbl.pack(side="left")

        ctk.CTkButton(bottom_row, text="Restore App", width=85, height=24, font=("Segoe UI", 10), command=self.restore_from_mini).pack(side="right")

    def update_mini_widget(self, pct, speed_str, fname):
        if self.mini_widget_window is not None and self.mini_widget_window.winfo_exists():
            self.mini_bar.set(pct / 100.0)
            self.mini_title_lbl.configure(text=f"⬇ {fname[:34]}")
            self.mini_stats_lbl.configure(text=f"{pct:.1f}%   |   {speed_str}")

    def restore_from_mini(self):
        self.deiconify()
        self.lift()
        if self.mini_widget_window is not None and self.mini_widget_window.winfo_exists():
            self.mini_widget_window.destroy()

    # ==================== BACKGROUND SCHEDULER ====================

    def scheduler_tick(self):
        now_hm = datetime.now().strftime("%H:%M")
        for item_id, task_info in list(self.active_tasks.items()):
            rec = task_info["record"]
            if rec.get("status") == "Scheduled":
                sched_t = rec.get("options", {}).get("schedule_time", "")
                if sched_t == now_hm:
                    rec["status"] = "Queued"
                    self.refresh_grid_view()
                    self.show_toast("Scheduled Download Started ⏰", rec["name"], "#3B8ED0")
                    threading.Thread(target=self.execute_single_download, args=(item_id,), daemon=True).start()
        self.after(5000, self.scheduler_tick)

    # ==================== TABLE SELECTION, FILTERING & PERSISTENT JSON ====================

    def on_category_selected(self, event=None):
        sel = self.tree_categories.selection()
        if sel:
            self.current_category_filter = sel[0]
            self.filter_status_lbl.configure(text=f"Showing: {self.current_category_filter}  (Right-Click for options)")
            self.refresh_grid_view()

    def on_grid_selection_change(self, event=None):
        selected_ids = set(self.tree_grid.selection())
        for iid in self.tree_grid.get_children():
            self.tree_grid.set(iid, "select", "☑️" if iid in selected_ids else "⬜")

    def select_all_rows(self):
        all_items = self.tree_grid.get_children()
        self.tree_grid.selection_set(all_items)
        self.on_grid_selection_change()

    def deselect_all_rows(self):
        self.tree_grid.selection_remove(self.tree_grid.selection())
        self.on_grid_selection_change()

    def refresh_grid_view(self):
        selected_before = set(self.tree_grid.selection())
        self.tree_grid.delete(*self.tree_grid.get_children())

        cat = self.current_category_filter
        for rec in self.history_records:
            st = rec.get("status", "")
            tp = rec.get("type", "")

            if cat == "Videos (MP4)" and tp != "MP4":
                continue
            elif cat == "Music (MP3)" and tp not in ("MP3", "FLAC", "WAV"):
                continue
            elif cat == "Completed" and st != "Completed":
                continue
            elif cat == "Active / Queued" and st not in ("Downloading", "Queued", "Paused", "Merging...", "Converting MP3..."):
                continue
            elif cat == "Scheduled" and st != "Scheduled":
                continue
            elif cat == "Deleted / Cancelled" and st not in ("Deleted", "Cancelled", "Error"):
                continue

            iid = rec["id"]
            chk = "☑️" if iid in selected_before else "⬜"
            self.tree_grid.insert("", "end", iid=iid, values=(
                chk, rec.get("name"), rec.get("size"), rec.get("progress_bar"),
                st, rec.get("eta"), rec.get("speed"), tp, rec.get("date")
            ))
            if iid in selected_before:
                self.tree_grid.selection_add(iid)

    def save_history_to_json(self, custom_path=HISTORY_FILE):
        try:
            with open(custom_path, "w", encoding="utf-8") as f:
                json.dump(self.history_records, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"JSON Save Error: {e}")

    def load_history_from_json(self, custom_path=HISTORY_FILE):
        if not os.path.exists(custom_path):
            return
        try:
            with open(custom_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.history_records = data
                for rec in self.history_records:
                    iid = rec.get("id", f"dl_{int(time.time()*1000)}")
                    rec["id"] = iid
                    if iid not in self.active_tasks:
                        self.active_tasks[iid] = {"cancel": False, "pause": False, "record": rec}
                self.refresh_grid_view()
        except Exception as e:
            print(f"JSON Load Error: {e}")

    # ==================== ITEM CONTROLS ====================

    def pause_selected_items(self):
        for iid in self.tree_grid.selection():
            if iid in self.active_tasks:
                self.active_tasks[iid]["pause"] = True
                self.active_tasks[iid]["record"]["status"] = "Paused"
        self.refresh_grid_view()
        self.save_history_to_json()

    def resume_selected_items(self):
        for iid in self.tree_grid.selection():
            if iid in self.active_tasks:
                t = self.active_tasks[iid]
                if t["record"]["status"] in ("Paused", "Cancelled", "Error", "Deleted"):
                    t["pause"] = False
                    t["cancel"] = False
                    t["record"]["status"] = "Downloading"
                    threading.Thread(target=self.execute_single_download, args=(iid,), daemon=True).start()
        self.refresh_grid_view()

    def stop_selected_items(self):
        for iid in self.tree_grid.selection():
            if iid in self.active_tasks:
                self.active_tasks[iid]["cancel"] = True
                self.active_tasks[iid]["record"]["status"] = "Cancelled"
        self.refresh_grid_view()
        self.save_history_to_json()

    def delete_selected_items(self):
        sel = self.tree_grid.selection()
        if not sel:
            messagebox.showwarning("Select Items", "Please select one or more items from the table first.")
            return
        for iid in sel:
            if iid in self.active_tasks:
                self.active_tasks[iid]["cancel"] = True
                self.active_tasks[iid]["record"]["status"] = "Deleted"
                self.active_tasks[iid]["record"]["speed"] = "--"
        self.refresh_grid_view()
        self.save_history_to_json()
        self.show_toast("Items Marked Deleted 🗑", f"{len(sel)} item(s) moved to Deleted history.", "#F39C12")

    def permanently_remove_selected(self):
        sel = set(self.tree_grid.selection())
        if not sel:
            return
        for iid in sel:
            if iid in self.active_tasks:
                self.active_tasks[iid]["cancel"] = True
                del self.active_tasks[iid]
        self.history_records = [r for r in self.history_records if r.get("id") not in sel]
        self.refresh_grid_view()
        self.save_history_to_json()

    def clear_completed_entries(self):
        self.history_records = [r for r in self.history_records if r.get("status") != "Completed"]
        self.refresh_grid_view()
        self.save_history_to_json()

    def pause_all_items(self):
        for t in self.active_tasks.values():
            if t["record"]["status"] == "Downloading":
                t["pause"] = True
                t["record"]["status"] = "Paused"
        self.refresh_grid_view()

    def resume_all_items(self):
        for iid, t in self.active_tasks.items():
            if t["record"]["status"] == "Paused":
                t["pause"] = False
        self.refresh_grid_view()

    def stop_all_items(self):
        for t in self.active_tasks.values():
            t["cancel"] = True
            if t["record"]["status"] == "Downloading":
                t["record"]["status"] = "Cancelled"
        self.refresh_grid_view()
        self.save_history_to_json()

    # ==================== EXTRA TOOLS ====================

    def import_urls_from_txt(self):
        fpath = filedialog.askopenfilename(title="Select TXT File with URLs", filetypes=[("Text Files", "*.txt")])
        if not fpath:
            return
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                links = [line.strip() for line in f if line.strip().startswith("http")]
            if links:
                for u in links:
                    threading.Thread(target=self.prepare_downloads, args=(u, {"quality": "1080p (Full HD) (MP4)"}), daemon=True).start()
                self.show_toast("Batch Import Started 📥", f"Queued {len(links)} links from TXT file.", "#2ECC71")
        except Exception as e:
            messagebox.showerror("Import Error", str(e))

    def export_json_history(self):
        fpath = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json")], title="Export Download History")
        if fpath:
            self.save_history_to_json(fpath)
            self.show_toast("History Exported 💾", os.path.basename(fpath), "#2ECC71")

    def import_json_history(self):
        fpath = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")], title="Import Download History")
        if fpath:
            self.load_history_from_json(fpath)
            self.save_history_to_json()
            self.show_toast("History Imported 📂", os.path.basename(fpath), "#3B8ED0")

    def select_cookies_file(self):
        fpath = filedialog.askopenfilename(title="Select Netscape cookies.txt File", filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")])
        if fpath:
            self.cookies_path = fpath
            self.cookies_badge.configure(text="🍪 Cookies: Active", fg_color="#27AE60")
            self.show_toast("Cookies Loaded 🍪", os.path.basename(fpath), "#2ECC71")
        else:
            self.cookies_path = ""
            self.cookies_badge.configure(text="🍪 Cookies: Off", fg_color="#444444")

    def update_ytdlp_engine(self):
        self.show_toast("Updating Engine ⚡", "Checking latest yt-dlp version via pip...", "#3B8ED0")

        def run_update():
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"])
                self.after(0, lambda: self.show_toast("Engine Updated ✔", "yt-dlp is now on the latest version!", "#2ECC71"))
            except Exception:
                self.after(0, lambda: self.show_toast("Update Failed ✖", "Could not update yt-dlp automatically.", "#E74C3C"))

        threading.Thread(target=run_update, daemon=True).start()

    def check_ffmpeg_status(self):
        try:
            subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            messagebox.showinfo("FFmpeg Status ✔", "FFmpeg is installed and recognized properly!\n4K Merging & MP3 Conversion are fully active.")
        except Exception:
            messagebox.showwarning("FFmpeg Missing ⚠", "FFmpeg was not found in system PATH.\nInstall it via: winget install Gyan.FFmpeg")

    def show_about_dialog(self):
        messagebox.showinfo(
            "About IDM Pro Ultimate",
            "YouTube & Universal IDM Pro - Ultimate Edition\n\n"
            "✔ 1-Click YouTube Browser Extension & Protocol Bridge\n"
            "✔ Multi-threaded Parallel Playlist Engine\n"
            "✔ Full Right-Click Context Menu & Direct Media Player\n"
            "✔ Live Thumbnail Preview & Video Trimmer\n"
            "✔ Persistent JSON Database (Completed / Deleted)"
        )

    def browse_folder(self):
        selected_dir = filedialog.askdirectory(initialdir=self.output_path_var.get(), title="Select Output Folder")
        if selected_dir:
            self.output_path_var.set(selected_dir)

    def open_output_folder(self):
        folder = self.output_path_var.get()
        os.makedirs(folder, exist_ok=True)
        if platform.system() == "Windows":
            os.startfile(folder)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    def check_clipboard(self, event=None):
        try:
            clip = self.clipboard_get().strip()
            supported_domains = ("youtube.com/", "youtu.be/", "tiktok.com/", "facebook.com/", "fb.watch/", "instagram.com/", "twitter.com/", "x.com/", "twitch.tv/", "soundcloud.com/")
            if any(d in clip for d in supported_domains) and clip != self.last_detected_url:
                self.last_detected_url = clip
                self.show_toast("Media Link Detected 📋", "Click '+ Add URL' to scan & download!", "#3B8ED0")
        except Exception:
            pass

    def check_queue_auto_stop(self, save_dir):
        active_left = any(r.get("status") in ("Downloading", "Queued", "Merging...", "Converting MP3...") for r in self.history_records)
        if not active_left:
            if messagebox.askyesno("Queue Finished ✔", "All queued downloads have finished!\n\nOpen folder and close application?"):
                self.open_output_folder()
                self.on_closing()

    def on_closing(self):
        self.save_history_to_json()
        self.destroy()


if __name__ == "__main__":
    # فحص ما إذا كان البرنامج قد تم استدعاؤه من المتصفح عبر البروتوكول ytidm://
    incoming_url = ""
    if len(sys.argv) > 1:
        incoming_url = extract_protocol_url(sys.argv[1])

    # محاولة إرسال الرابط للنسخة المفتوحة حالياً من البرنامج (حتى لا يفتح نافذتين)
    if incoming_url:
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(1.0)
            client.connect(("127.0.0.1", SINGLE_INSTANCE_PORT))
            client.sendall(incoming_url.encode("utf-8"))
            client.close()
            sys.exit(0)  # تم تسليم الرابط للنسخة المفتوحة بنجاح، نغلق النسخة الجديدة
        except Exception:
            pass  # البرنامج غير مفتوح حالياً، استمر في فتحه بشكل طبيعي مع تمرير الرابط

    app = IDMProUltimate(startup_url=incoming_url)
    app.mainloop()
