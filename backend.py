import http.server
import socketserver
import os
import json
import subprocess
import time
import threading
import random
import sys
import requests
import re
import glob
import mimetypes
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk
from datetime import datetime, timedelta

# --- 1. KONFIGURATION ---
TMDB_API_KEY = "04c35731a5ee918f014970082a0088b1"

if getattr(sys, 'frozen', False):
    BASE_PATH = os.path.dirname(sys.executable)
else:
    BASE_PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_PATH)

DEFAULT_PORT = 8000
FFMPEG_PATH = os.path.join(BASE_PATH, "ffmpeg.exe")
FFPROBE_PATH = os.path.join(BASE_PATH, "ffprobe.exe")
CONFIG_FILE = os.path.join(BASE_PATH, "filmnet_final_slots.json")
TRAILER_DIR = os.path.join(BASE_PATH, "trailers")
BUMPER_DIR = os.path.join(BASE_PATH, "bumpers")

if not os.path.exists(TRAILER_DIR): os.makedirs(TRAILER_DIR)
if not os.path.exists(BUMPER_DIR): os.makedirs(BUMPER_DIR)

CLUBS = {
    "Morning Club": {"slots": [7, 9, 11, 13], "color": "#fbc02d"},
    "Royal Club":   {"slots": [15, 17, 19, 21], "color": "#ffffff"},
    "Night Club":   {"slots": [23, 1, 3, 5], "color": "#b39ddb"}
}

# --- 2. FRONTEND HTML (Fallback) ---
INDEX_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Filmnet Monitor</title></head>
<body><h1>Filmnet Server Running</h1><p>Använd React-appen för att titta.</p></body>
</html>
"""

# --- 3. BACKEND APPLIKATION ---

class FilmnetApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FILMNET PRO - SYNC MASTER")
        self.root.geometry("1100x850")
        
        self.broadcast_proc = None
        self.feeder_proc = None
        self.active_club = None
        self.is_running = False
        self.is_gap_state = False 
        
        self.playlists = {c: [] for c in CLUBS}
        self.shuffled_daily = {c: [] for c in CLUBS}
        self.movie_meta = {}
        self.duration_cache = {}
        self.last_shuffle_date = ""

        self.hw_encoder = "libx264"
        self.hw_accel_args = []
        self.hw_name = "CPU (Väntar på scan...)"

        self.setup_ui()
        self.load_config()
        self.cleanup_temp_files()

        self.server_thread = threading.Thread(target=self.run_web_server, daemon=True)
        self.server_thread.start()
        self.log(f"🌐 Server redo på port {DEFAULT_PORT}")

        # Starta GUI-timern
        self.update_gui_timer()

    def setup_ui(self):
        top = tk.Frame(self.root, pady=10); top.pack(fill=tk.X)
        
        # Startknapp
        self.btn_master = tk.Button(top, text="STARTA MOTOR", bg="green", fg="white", font=("Arial", 11, "bold"), height=2, width=18, command=self.toggle_system)
        self.btn_master.pack(side=tk.LEFT, padx=10)
        
        # Status Label
        self.lbl_status = tk.Label(top, text="Motor: Avstängd", fg="#555", font=("Arial", 10, "bold"))
        self.lbl_status.pack(side=tk.LEFT, padx=10)

        # NYTT: Nedräkningsklocka
        self.lbl_countdown = tk.Label(top, text="--:--:--", fg="#0f0", bg="black", font=("Consolas", 16, "bold"), width=10)
        self.lbl_countdown.pack(side=tk.RIGHT, padx=20)

        self.tabs = ttk.Notebook(self.root); self.tabs.pack(fill=tk.BOTH, expand=True, padx=10)
        self.tab_widgets = {}
        for club in CLUBS:
            tab = tk.Frame(self.tabs); self.tabs.add(tab, text=club)
            lb = tk.Listbox(tab, font=("Arial", 10)); lb.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
            btns = tk.Frame(tab); btns.pack(fill=tk.X, padx=10, pady=5)
            tk.Button(btns, text="➕ Lägg till", command=lambda c=club: self.add_files(c)).pack(side=tk.LEFT, padx=2)
            tk.Button(btns, text="🗑 Ta bort", command=lambda c=club, l=lb: self.remove_item(c, l)).pack(side=tk.LEFT, padx=2)
            self.tab_widgets[club] = lb

        self.log_box = scrolledtext.ScrolledText(self.root, height=8, bg="#000", fg="#0f0", font=("Consolas", 9))
        self.log_box.pack(fill=tk.X, padx=10, pady=10)

    # --- TIMER FUNKTION ---
    def update_gui_timer(self):
        if self.is_running:
            try:
                slot, elapsed, next_start, _ = self.get_slot_info()
                movie_path = self.get_assigned_movie(slot['club'], slot['hour'])
                
                if movie_path:
                    total_dur = self.get_duration(movie_path)
                    remaining = total_dur - elapsed
                    
                    if remaining > 0:
                        # Film spelas: Visa tid kvar
                        m, s = divmod(int(remaining), 60)
                        h, m = divmod(m, 60)
                        self.lbl_countdown.config(text=f"{h:02d}:{m:02d}:{s:02d}", fg="#0f0", bg="black")
                    else:
                        # Pausläge
                        self.lbl_countdown.config(text="PAUS", fg="yellow", bg="#333")
                else:
                    self.lbl_countdown.config(text="NO FLM", fg="red", bg="black")
            except:
                self.lbl_countdown.config(text="ERR", fg="red")
        else:
            self.lbl_countdown.config(text="OFF", fg="#555", bg="#ddd")
        
        self.root.after(1000, self.update_gui_timer)

    def cleanup_temp_files(self):
        self.log("🧹 Städar filer...")
        for f in glob.glob(os.path.join(BASE_PATH, "stream*.ts")):
            try: os.remove(f)
            except: pass
        if os.path.exists(os.path.join(BASE_PATH, "stream.m3u8")):
            try: os.remove(os.path.join(BASE_PATH, "stream.m3u8"))
            except: pass

    def remove_item(self, club, lb):
        selection = lb.curselection()
        if not selection: return
        for i in reversed(selection): self.playlists[club].pop(i)
        self.shuffled_daily[club] = [] 
        self.last_shuffle_date = ""  
        self.refresh_ui(); self.save_config()
        self.log(f"🗑 Tog bort film(er) från {club}. Schemat nollställdes.")

    def detect_best_encoder(self):
        self.log("🕵️ Scannar efter grafikkort...")
        candidates = [
            ("h264_nvenc", ["-hwaccel", "cuda"], "NVIDIA GPU (NVENC) 🚀"),
            ("h264_qsv", ["-hwaccel", "qsv"], "INTEL GPU (QuickSync) ⚡"),
            ("h264_amf", [], "AMD GPU (AMF) ⚡"),
            ("libx264", [], "CPU (Mjukvara/Säker) 🐢")
        ]
        si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        for enc, args, name in candidates:
            try:
                cmd = [FFMPEG_PATH, "-v", "error", "-f", "lavfi", "-i", "color=black:s=640x360", "-t", "1"] + args + ["-c:v", enc, "-f", "null", "-"]
                if subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, startupinfo=si).returncode == 0:
                    self.hw_encoder = enc; self.hw_accel_args = args; self.hw_name = name
                    self.log(f"✅ Hårdvara: {name}"); self.lbl_status.config(text=f"Motor: {name}", fg="#0000AA")
                    return
            except: pass
        self.hw_encoder = "libx264"; self.hw_accel_args = []; self.hw_name = "CPU (Fallback)"
        self.lbl_status.config(text="Motor: CPU", fg="red")

    def toggle_system(self):
        if not self.is_running:
            self.is_running = True
            self.btn_master.config(text="STOPPA MOTOR", bg="red")
            self.cleanup_temp_files()
            self.detect_best_encoder()
            self.check_daily_shuffle()
            threading.Thread(target=self.run_broadcast_loop, daemon=True).start()
        else:
            self.is_running = False
            self.btn_master.config(text="STARTA MOTOR", bg="green")
            if self.feeder_proc: self.feeder_proc.kill()
            if self.broadcast_proc: self.broadcast_proc.kill()
            threading.Thread(target=self.cleanup_temp_files, daemon=True).start()

    def run_broadcast_loop(self):
        si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        self.broadcast_proc = subprocess.Popen(
            [FFMPEG_PATH, "-re", "-i", "-", "-c:v", "copy", "-c:a", "copy", 
             "-f", "hls", "-hls_time", "4", "-hls_list_size", "5", 
             "-hls_flags", "delete_segments", "stream.m3u8"], 
            stdin=subprocess.PIPE, startupinfo=si
        )
        
        preset = "ultrafast"
        if "nvenc" in self.hw_encoder: preset = "p4"
        elif "qsv" in self.hw_encoder: preset = "veryfast"
        elif "amf" in self.hw_encoder: preset = "speed"

        while self.is_running:
            self.check_daily_shuffle()
            slot, elapsed, next_start_dt, next_slot_obj = self.get_slot_info()
            self.active_club = slot['club']
            movie_path = self.get_assigned_movie(self.active_club, slot['hour'])
            
            if not movie_path: 
                self.log(f"⚠️ Ingen film i slot {slot['hour']}:00. Spelar standby...")
                self.is_gap_state = False
                self.play_standby_loop(si, preset, 5)
                continue
            
            dur = self.get_duration(movie_path)
            
            # --- FILM-LÄGE ---
            if elapsed < dur:
                self.is_gap_state = False
                meta = self.fetch_tmdb(movie_path)
                self.log(f"🎬 Spelar: {meta['tmdb_title']} (Encoder: {self.hw_encoder})")
                
                if self.feeder_proc:
                    try: self.feeder_proc.kill(); self.feeder_proc.wait(timeout=1)
                    except: pass
                
                time.sleep(0.5)
                logo_path = os.path.join(BASE_PATH, "logo.png")
                has_logo = os.path.exists(logo_path)

                cmd = [FFMPEG_PATH] + self.hw_accel_args + ["-re", "-ss", str(elapsed), "-i", movie_path]
                if has_logo: cmd += ["-i", logo_path]
                cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
                
                cmd += ["-c:v", self.hw_encoder, "-preset", preset]
                if "nvenc" in self.hw_encoder: cmd += ["-tune", "zerolatency", "-rc", "cbr"]

                base_filter = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
                
                if has_logo:
                    cmd += ["-filter_complex", f"[0:v]{base_filter}[bg];[bg][1:v]overlay=main_w-overlay_w-30:30[v_out]", "-map", "[v_out]"]
                    dummy_audio_idx = "2"
                else:
                    cmd += ["-filter_complex", f"[0:v]{base_filter}[v_out]", "-map", "[v_out]"]
                    dummy_audio_idx = "1"
                
                cmd += ["-map", "0:a?", "-map", f"{dummy_audio_idx}:a"]
                cmd += ["-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000", "-f", "mpegts", "-"]
                
                self.feeder_proc = subprocess.Popen(cmd, stdout=self.broadcast_proc.stdin, stderr=subprocess.DEVNULL, startupinfo=si)
                self.feeder_proc.wait()
            
            # --- GAP-LÄGE ---
            self.handle_gap(next_start_dt, si, preset)

    def handle_gap(self, next_start_dt, si, preset):
        trailers = glob.glob(os.path.join(TRAILER_DIR, "*.*"))
        bumpers = glob.glob(os.path.join(BUMPER_DIR, "*.*"))
        
        while self.is_running:
            remaining = (next_start_dt - datetime.now()).total_seconds()
            
            # 1. STOPPA DIREKT VID 0.1s KVAR
            if remaining <= 0.1:
                if self.feeder_proc: 
                    try: self.feeder_proc.kill() 
                    except: pass
                break 
            
            # 2. Sista 5 sekunderna kör vi bara standby för ren start
            if remaining < 5:
                self.is_gap_state = True
                self.play_standby_loop(si, preset, remaining)
                continue

            self.is_gap_state = True
            t = None
            if remaining < 60 and bumpers: t = random.choice(bumpers)
            elif trailers: t = random.choice(trailers)

            if t:
                self.log(f"🎞️ Utfyllnad: {os.path.basename(t)}")
                cmd = [FFMPEG_PATH] + self.hw_accel_args + ["-re", "-i", t]
                cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
                cmd += ["-c:v", self.hw_encoder, "-preset", preset]
                if "nvenc" in self.hw_encoder: cmd += ["-tune", "zerolatency"]
                
                cmd += ["-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"]
                cmd += ["-map", "0:v", "-map", "0:a?", "-map", "1:a"]
                cmd += ["-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000", "-f", "mpegts", "-"]
                
                self.feeder_proc = subprocess.Popen(cmd, stdout=self.broadcast_proc.stdin, stderr=subprocess.DEVNULL, startupinfo=si)
                
                while self.feeder_proc.poll() is None:
                    # HÅRD KOLL: Om tiden är ute, döda direkt
                    if (next_start_dt - datetime.now()).total_seconds() <= 0.1:
                        self.feeder_proc.kill()
                        break
                    time.sleep(0.1)
            else:
                self.play_standby_loop(si, preset, 5)

    def play_standby_loop(self, si, preset, seconds):
        if seconds <= 0: return
        cmd = [FFMPEG_PATH, "-re", "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=25", "-t", str(seconds)]
        cmd += ["-c:v", "libx264", "-preset", "ultrafast"]
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        cmd += ["-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000", "-f", "mpegts", "-"]
        
        self.feeder_proc = subprocess.Popen(cmd, stdout=self.broadcast_proc.stdin, stderr=subprocess.DEVNULL, startupinfo=si)
        self.feeder_proc.wait()

    def check_daily_shuffle(self):
        d = datetime.now().strftime("%Y-%m-%d")
        if d != self.last_shuffle_date or not any(self.shuffled_daily.values()):
            self.log(f"🔄 Blandar spellistor för {d}")
            seed_val = int(d.replace("-", ""))
            rng = random.Random(seed_val)
            for c in CLUBS:
                t = list(self.playlists[c]); t.sort(); rng.shuffle(t)
                self.shuffled_daily[c] = t
            self.last_shuffle_date = d; self.save_config()

    def get_slot_info(self):
        now = datetime.now()
        cur_h = now.hour
        all_s = []
        for c, cfg in CLUBS.items():
            for s in cfg['slots']: 
                sort_val = s if s >= 6 else s + 24
                all_s.append({"club": c, "hour": s, "sort_val": sort_val})
        all_s.sort(key=lambda x: x['sort_val'])
        cur_sort_val = cur_h if cur_h >= 6 else cur_h + 24
        active_idx = 0
        for i in range(len(all_s)):
            this_slot = all_s[i]
            next_slot_idx = (i + 1) % len(all_s)
            next_s_val = all_s[next_slot_idx]['sort_val']
            if next_slot_idx == 0: next_s_val += 24
            if this_slot['sort_val'] <= cur_sort_val < next_s_val:
                active_idx = i; break
        active = all_s[active_idx]
        next_slot = all_s[(active_idx + 1) % len(all_s)]
        s_start = now.replace(hour=active['hour'], minute=0, second=0, microsecond=0)
        if s_start > now: s_start -= timedelta(days=1)
        n_start = now.replace(hour=next_slot['hour'], minute=0, second=0, microsecond=0)
        if n_start <= now: n_start += timedelta(days=1)
        return active, (now - s_start).total_seconds(), n_start, next_slot

    def get_assigned_movie(self, club, slot_hour):
        playlist = self.shuffled_daily.get(club, [])
        if not playlist: return None
        slots = CLUBS[club]['slots']
        if slot_hour not in slots: return None
        return playlist[slots.index(slot_hour) % len(playlist)]

    def fetch_tmdb(self, path):
        if not path: return {}
        if path in self.movie_meta: return self.movie_meta[path]
        fn = os.path.basename(path)
        y = re.search(r"(\d{4})", fn); yr = y.group(1) if y else ""
        nm = fn.split(yr)[0] if yr else fn.rsplit('.', 1)[0]
        cl = nm.replace('.', ' ').replace('-', ' ').replace('_', ' ').strip()
        try:
            r = requests.get(f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={cl}&language=sv-SE&primary_release_year={yr}", timeout=2).json()
            if not r.get('results'): r = requests.get(f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={cl}&language=en-US&primary_release_year={yr}", timeout=2).json()
            if r.get('results'):
                res = r['results'][0]
                self.movie_meta[path] = {"tmdb_title": res['title'],"plot": res['overview'],"poster": f"https://image.tmdb.org/t/p/w500{res['poster_path']}" if res.get('poster_path') else ""}
                return self.movie_meta[path]
        except: pass
        return {"tmdb_title": fn, "plot": "Info saknas.", "poster": ""}

    def get_duration(self, p):
        if p in self.duration_cache: return self.duration_cache[p]
        try:
            cmd = [FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", p]
            val = float(subprocess.check_output(cmd, startupinfo=subprocess.STARTUPINFO()).decode().strip())
            self.duration_cache[p] = val; return val
        except: return 7200

    def add_files(self, club):
        files = filedialog.askopenfilenames(filetypes=[("Video", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.m4v *.ts")])
        if files:
            for f in files: self.playlists[club].append(f); threading.Thread(target=lambda: self.fetch_tmdb(f), daemon=True).start()
            self.last_shuffle_date = ""; self.refresh_ui(); self.save_config()

    def refresh_ui(self):
        for c, lb in self.tab_widgets.items(): lb.delete(0, tk.END); [lb.insert(tk.END, os.path.basename(p)) for p in self.playlists[c]]

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f: d = json.load(f); self.playlists = d.get("lists", self.playlists); self.movie_meta = d.get("meta", {})
                self.refresh_ui()
            except: pass

    # --- FIXAD SAVE_CONFIG (Syntax Error Fixed) ---
    def save_config(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump({"lists": self.playlists, "meta": self.movie_meta}, f)
        except:
            pass

    def log(self, m):
        try: self.log_box.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {m}\n"); self.log_box.see(tk.END)
        except: pass

    def run_web_server(self):
        if not mimetypes.inited: mimetypes.init()
        mimetypes.add_type('application/vnd.apple.mpegurl', '.m3u8')
        mimetypes.add_type('video/mp2t', '.ts')
        gui = self
        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a): pass
            def end_headers(self):
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
                super().end_headers()
            def do_OPTIONS(self): self.send_response(200); self.end_headers()
            def do_GET(self):
                if self.path == '/api/status':
                    self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
                    try:
                        cur, elapsed, next_dt, next_obj = gui.get_slot_info()
                        now_path = gui.get_assigned_movie(cur['club'], cur['hour'])
                        now_meta = gui.fetch_tmdb(now_path) if now_path else {"tmdb_title": "Ingen sändning", "plot": "", "poster": ""}
                        next_path = gui.get_assigned_movie(next_obj['club'], next_obj['hour'])
                        next_meta = gui.fetch_tmdb(next_path) if next_path else {"tmdb_title": "Slut för idag", "plot": "", "poster": ""}
                        schedules = {}
                        for cn in CLUBS:
                            schedules[cn] = []
                            for s_hour in CLUBS[cn]['slots']:
                                m_path = gui.get_assigned_movie(cn, s_hour)
                                m_title = gui.fetch_tmdb(m_path)['tmdb_title'] if m_path else "TBA"
                                schedules[cn].append({"time": f"{s_hour:02d}:00", "title": m_title, "is_current": (cn == cur['club'] and s_hour == cur['hour'])})
                        gap_sec = int((next_dt - datetime.now()).total_seconds())
                        resp = {"active_club": cur['club'], "active_color": CLUBS[cur['club']]['color'], "is_gap": gui.is_gap_state, "gap_time": f"{gap_sec//60:02d}:{gap_sec%60:02d}", "playing_now": now_meta, "next_movie": next_meta, "all_schedules": schedules}
                        self.wfile.write(json.dumps(resp).encode())
                    except: self.wfile.write(json.dumps({}).encode())
                else: super().do_GET()
        socketserver.TCPServer.allow_reuse_address = True
        try:
            with socketserver.ThreadingTCPServer(("", DEFAULT_PORT), Handler) as httpd: httpd.serve_forever()
        except: pass

if __name__ == "__main__":
    root = tk.Tk(); app = FilmnetApp(root); root.mainloop()