#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DualCrypt GUI

GUI wrapper for DualCrypt.py with:
- Real-time logs
- Progress bar
- Theme toggle (Light/Dark)
- Remember last settings
- Per-file timing and total elapsed time
- Export logs to .txt
- Open output folder
- Process subset of files (choose specific .html files)
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import sys
import os
from pathlib import Path
import threading
import queue
import time
import json

SCRIPT_NAME = "DualCrypt.py"
SETTINGS_FILE = "settings.json"

# ----------------- Persistence -----------------
def load_settings(base_dir: Path):
    p = base_dir / SETTINGS_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_settings(base_dir: Path, data: dict):
    p = base_dir / SETTINGS_FILE
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

# ----------------- Worker -----------------
class Worker(threading.Thread):
    def __init__(self, src, dst, mode, minify, protect, selected_files, log_q, progress_cb, done_cb):
        super().__init__(daemon=True)
        self.src = Path(src)
        self.dst = Path(dst)
        self.mode = mode
        self.minify = minify
        self.protect = protect
        self.selected_files = [Path(p) for p in (selected_files or [])]
        self.log_q = log_q
        self.progress_cb = progress_cb
        self.done_cb = done_cb
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            t0 = time.time()
            if not self.src.exists():
                self.log_q.put("[ERR] Source directory not found: %s\n" % self.src)
                self.done_cb(False, 0.0)
                return

            # enumerate files
            if self.selected_files:
                files = []
                for p in self.selected_files:
                    if p.exists() and p.suffix.lower() == ".html":
                        try:
                            _ = p.relative_to(self.src)  # ensure inside src
                            files.append(p)
                        except ValueError:
                            self.log_q.put(f"[WARN] Skipped (not under src): {p}\n")
                    else:
                        self.log_q.put(f"[WARN] Skipped (missing/not .html): {p}\n")
            else:
                files = [p for p in self.src.rglob("*.html") if p.is_file()]

            total = len(files)
            if total == 0:
                self.log_q.put("[INFO] No .html files to process.\n")
                self.done_cb(False, 0.0)
                return

            self.log_q.put("[INFO] Files to process: %d\n" % total)
            self.progress_cb(0, total)

            pyexe = sys.executable if sys.executable else "python"
            base_cwd = os.path.dirname(os.path.abspath(__file__))

            for idx, f in enumerate(files, start=1):
                if self._stop.is_set():
                    self.log_q.put("[WARN] Canceled by user.\n")
                    self.done_cb(False, time.time() - t0)
                    return

                rel = f.relative_to(self.src).as_posix()  # glob relative pattern
                cmd = [pyexe, SCRIPT_NAME, "--src", str(self.src), "--dst", str(self.dst), "--mode", self.mode, "--glob", rel]
                if not self.minify:
                    cmd.append("--no-minify")
                if not self.protect:
                    cmd.append("--no-protect")

                self.log_q.put(f"[RUN] {rel}\n")
                f_start = time.time()
                try:
                    proc = subprocess.Popen(cmd, cwd=base_cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    for line in iter(proc.stdout.readline, ""):
                        if line:
                            self.log_q.put(line)
                        if self._stop.is_set():
                            proc.terminate()
                            self.log_q.put("[WARN] Terminating current task...\n")
                            self.done_cb(False, time.time() - t0)
                            return
                    proc.wait()
                    if proc.returncode != 0:
                        self.log_q.put(f"[ERR] Failed on {rel} (code {proc.returncode})\n")
                        self.done_cb(False, time.time() - t0)
                        return
                except Exception as e:
                    self.log_q.put(f"[EXC] {e}\n")
                    self.done_cb(False, time.time() - t0)
                    return

                f_elapsed = time.time() - f_start
                self.log_q.put(f"[OK] {rel} ({f_elapsed:.2f}s)\n")
                self.progress_cb(idx, total)

            total_elapsed = time.time() - t0
            self.log_q.put(f"[OK] All files processed. Total time: {total_elapsed:.2f}s\n")
            self.done_cb(True, total_elapsed)
        except Exception as e:
            self.log_q.put(f"[EXC] {e}\n")
            self.done_cb(False, 0.0)

# ----------------- UI Helpers -----------------
def append_log(text_widget, q):
    try:
        while True:
            line = q.get_nowait()
            text_widget.insert("end", line)
            text_widget.see("end")
    except queue.Empty:
        pass

def export_log(text_widget, base_dir: Path):
    content = text_widget.get("1.0", "end").strip()
    if not content:
        messagebox.showinfo("Export Log", "Log is empty.")
        return
    from tkinter import filedialog
    import datetime as _dt
    default = base_dir / f"log_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    path = filedialog.asksaveasfilename(
        title="Export Log to .txt",
        defaultextension=".txt",
        initialfile=str(default.name),
        filetypes=[("Text files", "*.txt")]
    )
    if path:
        try:
            Path(path).write_text(content, encoding="utf-8")
            messagebox.showinfo("Export Log", f"Saved: {path}")
        except Exception as e:
            messagebox.showerror("Export Log", str(e))

def open_output_folder(dst):
    if not dst:
        messagebox.showerror("Open Folder", "Please select Destination folder first.")
        return
    p = Path(dst)
    if not p.exists():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Open Folder", f"Cannot create folder: {e}")
            return
    # Open with OS default
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception as e:
        messagebox.showerror("Open Folder", str(e))

def run_worker(src, dst, mode, minify, protect, selected_files, text_widget, progbar, start_btn, stop_btn, base_dir, theme_var, src_var, dst_var, mode_var, minify_var, protect_var):
    if not src or not dst:
        messagebox.showerror("Error", "Please select both Source and Destination folders.")
        return

    # Save settings immediately
    save_settings(base_dir, {
        "src": src,
        "dst": dst,
        "mode": mode,
        "minify": bool(minify),
        "protect": bool(protect),
        "theme": theme_var.get()
    })

    # prepare UI
    text_widget.delete("1.0", "end")
    progbar["value"] = 0
    progbar["mode"] = "determinate"
    start_btn["state"] = "disabled"
    stop_btn["state"] = "normal"

    log_q = queue.Queue()

    def progress_cb(done, total):
        progbar["maximum"] = total
        progbar["value"] = done

    def done_cb(success, elapsed):
        start_btn["state"] = "normal"
        stop_btn["state"] = "disabled"
        if success:
            messagebox.showinfo("Completed", f"All files processed successfully.\nTotal time: {elapsed:.2f}s")
        else:
            messagebox.showwarning("Finished", "The operation finished with warnings or was canceled.")

    worker = Worker(src, dst, mode, minify, protect, selected_files, log_q, progress_cb, done_cb)
    worker.start()

    # poll logs
    def poll():
        append_log(text_widget, log_q)
        if worker.is_alive():
            text_widget.after(100, poll)
        else:
            append_log(text_widget, log_q)
    poll()

    # bind stop button
    def stop_now():
        worker.stop()
    stop_btn.config(command=stop_now)

# Theme application
def apply_theme(root, style, theme_name, log_widget=None):
    if theme_name == "Dark":
        try:
            style.theme_use("clam")
        except:
            pass
        bg = "#121212"
        fg = "#e0e0e0"
        root.configure(bg=bg)
        style.configure(".", background=bg, foreground=fg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TFrame", background=bg)
        style.configure("TButton", background="#1e1e1e", foreground=fg)
        style.configure("TRadiobutton", background=bg, foreground=fg)
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.configure("TEntry", fieldbackground="#1e1e1e", foreground=fg)
        style.configure("Horizontal.TProgressbar", background="#4caf50")
        if log_widget is not None:
            log_widget.configure(bg="#1e1e1e", fg="#e0e0e0", insertbackground="#e0e0e0")
    else:
        try:
            style.theme_use("vista")
        except:
            try:
                style.theme_use("clam")
            except:
                pass
        root.configure(bg="SystemButtonFace")
        style.configure(".", background="SystemButtonFace", foreground="black")
        style.configure("TFrame", background="SystemButtonFace")
        style.configure("Horizontal.TProgressbar", background="#4caf50")
        if log_widget is not None:
            log_widget.configure(bg="white", fg="black", insertbackground="black")

def main():
    base_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    settings = load_settings(base_dir)

    root = tk.Tk()
    try:
        root.iconphoto(True, tk.PhotoImage(file=str(base_dir / "icons" / "icon.png")))
    except Exception:
        pass

    try:
        root.iconphoto(False, tk.PhotoImage(file=str(Path(__file__).parent / 'icons' / 'icon.png')))
    except Exception:
        pass

    root.title("DualCrypt — GUI")
    root.geometry("920x640")
    root.minsize(880, 600)

    style = ttk.Style()
    theme_var = tk.StringVar(value=settings.get("theme", "Light"))

    # Vars with defaults from settings
    src_var = tk.StringVar(value=settings.get("src", ""))
    dst_var = tk.StringVar(value=settings.get("dst", ""))
    mode_var = tk.StringVar(value=settings.get("mode", "percent"))
    minify_var = tk.BooleanVar(value=settings.get("minify", True))
    protect_var = tk.BooleanVar(value=settings.get("protect", True))

    # Title
    title = ttk.Label(root, text="DualCrypt — GUI", font=("Segoe UI", 14, "bold"))
    title.pack(pady=(12,4))
    sub = ttk.Label(root, text="Developer: Knightnum Limited • https://knightnum.online")
    sub.pack(pady=(0,8))

    # Theme switch
    theme_frame = ttk.Frame(root, padding=(10, 0))
    theme_frame.pack(fill="x")
    ttk.Label(theme_frame, text="Theme:").pack(side="left")
    theme_combo = ttk.Combobox(theme_frame, values=["Light", "Dark"], state="readonly", width=8, textvariable=theme_var)
    theme_combo.pack(side="left", padx=8)

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)

    # Source
    f1 = ttk.Frame(frm)
    f1.pack(fill="x", pady=5)
    ttk.Label(f1, text="Source folder:").pack(side="left")
    ttk.Entry(f1, textvariable=src_var).pack(side="left", fill="x", expand=True, padx=8)
    ttk.Button(f1, text="Browse", command=lambda: src_var.set(filedialog.askdirectory() or src_var.get())).pack(side="left")

    # Destination
    f2 = ttk.Frame(frm)
    f2.pack(fill="x", pady=5)
    ttk.Label(f2, text="Destination folder:").pack(side="left")
    ttk.Entry(f2, textvariable=dst_var).pack(side="left", fill="x", expand=True, padx=8)
    ttk.Button(f2, text="Browse", command=lambda: dst_var.set(filedialog.askdirectory() or dst_var.get())).pack(side="left")

    # Options row (left)
    options_row = ttk.Frame(frm)
    options_row.pack(fill="x", pady=5)
    ttk.Label(options_row, text="Encoding:").pack(side="left")
    for label, value in [("Percent (unescape)", "percent"), ("Base64 (atob)", "base64"), ("Dual (Base64+Percent)", "dual")]:
        ttk.Radiobutton(options_row, text=label, value=value, variable=mode_var).pack(side="left", padx=6)
    ttk.Checkbutton(options_row, text="Light minify", variable=minify_var).pack(side="left", padx=10)
    ttk.Checkbutton(options_row, text="Protection (right-click / Ctrl+U / F12)", variable=protect_var).pack(side="left")

    # Subset selection
    subset_frame = ttk.Frame(frm)
    subset_frame.pack(fill="x", pady=(8,4))
    subset_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(subset_frame, text="Process only selected files", variable=subset_var).pack(side="left")
    selected_files = []

    files_frame = ttk.Frame(frm)
    files_frame.pack(fill="both", expand=False)
    listbox = tk.Listbox(files_frame, height=5, selectmode="extended")
    listbox.pack(side="left", fill="both", expand=True)
    sb = ttk.Scrollbar(files_frame, orient="vertical", command=listbox.yview)
    sb.pack(side="right", fill="y")
    listbox.configure(yscrollcommand=sb.set)

    def add_files():
        initdir = src_var.get() or str(base_dir)
        paths = filedialog.askopenfilenames(title="Select HTML files (under Source)", initialdir=initdir, filetypes=[("HTML files","*.html")])
        for p in paths:
            if p not in selected_files:
                selected_files.append(p)
                try:
                    rel = str(Path(p).resolve().relative_to(Path(src_var.get()).resolve()))
                except Exception:
                    rel = p
                listbox.insert("end", rel)

    def remove_selected():
        for idx in reversed(listbox.curselection()):
            del selected_files[idx]
            listbox.delete(idx)

    btns = ttk.Frame(frm)
    btns.pack(fill="x", pady=(2,8))
    ttk.Button(btns, text="Add files...", command=add_files).pack(side="left")
    ttk.Button(btns, text="Remove selected", command=remove_selected).pack(side="left", padx=6)

    # Progress + Actions
    f4 = ttk.Frame(frm)
    f4.pack(fill="x", pady=6)
    prog = ttk.Progressbar(f4, length=480, mode="determinate", maximum=100, value=0, style="Horizontal.TProgressbar")
    prog.pack(side="left", padx=(0,10))
    start_btn = ttk.Button(f4, text="Run", command=lambda: run_worker(
        src_var.get(), dst_var.get(), mode_var.get(), minify_var.get(), protect_var.get(),
        (selected_files if subset_var.get() else []), log, prog, start_btn, stop_btn, base_dir,
        theme_var, src_var, dst_var, mode_var, minify_var, protect_var))
    start_btn.pack(side="left")
    stop_btn = ttk.Button(f4, text="Stop")
    stop_btn["state"] = "disabled"
    stop_btn.pack(side="left", padx=6)

    # Extra action buttons
    f5 = ttk.Frame(frm)
    f5.pack(fill="x", pady=(4,8))
    ttk.Button(f5, text="Export Log...", command=lambda: export_log(log, base_dir)).pack(side="left")
    ttk.Button(f5, text="Open Output Folder", command=lambda: open_output_folder(dst_var.get())).pack(side="left", padx=8)

    # Log area
    log_frame = ttk.Frame(frm)
    log_frame.pack(fill="both", expand=True, pady=(8,0))
    log = tk.Text(log_frame, height=14, wrap="word")
    log.pack(side="left", fill="both", expand=True)
    yscroll = ttk.Scrollbar(log_frame, orient="vertical", command=log.yview)
    yscroll.pack(side="right", fill="y")
    log.configure(yscrollcommand=yscroll.set)

    # Theme hook
    def on_theme_change(event=None):
        apply_theme(root, style, theme_var.get(), log_widget=log)
        # Save theme immediately
        s = load_settings(base_dir)
        s["theme"] = theme_var.get()
        save_settings(base_dir, s)
    theme_combo.bind("<<ComboboxSelected>>", on_theme_change)
    apply_theme(root, style, theme_var.get(), log_widget=log)

    # Footer tip
    tip = ttk.Label(root, text="Tips: Settings (theme, folders, mode, options) are auto-saved. You can export logs or process only selected files.")
    tip.pack(pady=(4, 8))

    root.mainloop()

if __name__ == "__main__":
    main()
