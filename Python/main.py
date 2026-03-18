import json
import os
import hashlib
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from PIL import Image, ImageTk


DB_PATH = os.path.join(os.path.dirname(__file__), "students_db.json")
DEFAULT_ADMIN_PASSWORD = "admin" 


def auto_open_serial(serial_module):
    """Try to automatically find and open an Arduino-like serial port.
    Returns an open Serial instance or None."""
    try:
        ports = serial_module.tools.list_ports.comports()
    except Exception:
        try:
            import serial.tools.list_ports
            ports = serial.tools.list_ports.comports()
        except Exception:
            return None
    if not ports:
        return None
    priority_keywords = ["arduino", "ch340", "cp210", "ftdi", "usb serial", "usb"]
    candidates = []
    others = []
    for p in ports:
        info = " ".join([str(getattr(p, k, "")) for k in ("description", "hwid", "manufacturer") if getattr(p, k, None)])
        info_lower = info.lower()
        matched = False
        for kw in priority_keywords:
            if kw in info_lower:
                candidates.append(p)
                matched = True
                break
        if not matched:
            others.append(p)
    for p in (candidates + others):
        try:
            ser = serial_module.Serial(p.device, 115200, timeout=0.5)
            try:
                ser.reset_input_buffer()
            except Exception:
                pass
            return ser
        except Exception:
            continue
    return None

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def load_db():
    if not os.path.exists(DB_PATH):
        db = {
            "admin_password_hash": hash_password(DEFAULT_ADMIN_PASSWORD),
            "students": {},
            "logs": []
        }
        save_db(db)
        return db
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


class StudentApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Logbook System - AICS")
        self.db = load_db()
        # serial for RFID readers and relay control (auto-detect)
        try:
            import serial
            self.serial = auto_open_serial(serial)
        except Exception:
            self.serial = None
        self.pending_uid = None
        self.waiting_for_uid = False
        # polling state flag to avoid duplicate poll loops
        self._polling_active = False
        if self.serial:
            self._polling_active = True
            self.root.after(50, self._poll_serial)

        # Header frame
        header_frame = tk.Frame(root, bg="#1e3a8a", padx=10, pady=10)
        header_frame.pack(fill=tk.X, padx=0, pady=0)
        
        
        # Header text (center/right)
        header_text = ttk.Label(header_frame, text="Asian Institute of Computer Studies", 
                                font=("Arial", 18, "bold"))
        header_text.pack(expand=True)
        
        # Separator line
        separator = ttk.Frame(root, height=2)
        separator.pack(fill=tk.X, padx=0, pady=(0, 10))

        # Main frame with left controls and right Treeview
        frame = ttk.Frame(root, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        content = ttk.Frame(frame)
        content.pack(fill=tk.BOTH, expand=True)

        # Left controls column
        left_col = ttk.Frame(content, width=260, padding=(0, 0, 10, 0))
        left_col.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(left_col, text="Controls", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(0, 6))
        admin_btn_left = ttk.Button(left_col, text="Admin Login", command=self.open_admin_login)
        admin_btn_left.pack(fill=tk.X, pady=4)
        status_btn_left = ttk.Button(left_col, text="See All Status", command=self.open_students_window)
        status_btn_left.pack(fill=tk.X, pady=4)
        lock_btn = ttk.Button(left_col, text="Lock Arduino", command=lambda: self.send_lock())
        lock_btn.pack(fill=tk.X, pady=4)
        unlock_btn = ttk.Button(left_col, text="Unlock Arduino", command=lambda: self.send_unlock())
        unlock_btn.pack(fill=tk.X, pady=4)

        # Search area
        ttk.Separator(left_col, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(8, 8))
        search_frame = ttk.LabelFrame(left_col, text="Search", padding=6)
        search_frame.pack(fill=tk.X, pady=(0, 6))
        self.search_entry = ttk.Entry(search_frame)
        self.search_entry.pack(fill=tk.X, pady=4)
        clear_search_btn = ttk.Button(search_frame, text="Clear Search", command=lambda: (self.search_entry.delete(0, tk.END), self.refresh_logs()))
        clear_search_btn.pack(fill=tk.X, pady=2)
        # Live search: filter on each key release
        self.search_entry.bind("<KeyRelease>", lambda e: self.filter_logs(self.search_entry.get().strip()))
        self.search_entry.bind("<Return>", lambda e: self.filter_logs(self.search_entry.get().strip()))

        # Output label
        self.output_var = tk.StringVar(value="Result will appear here")
        self.output_label = ttk.Label(left_col, textvariable=self.output_var, padding=(0, 8), wraplength=240)
        self.output_label.pack(fill=tk.X, pady=(6, 0))

        # Right: Treeview area
        right_col = ttk.Frame(content)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Table (Treeview)
        cols = ("timestamp", "id", "name", "section", "action")
        self.tree = ttk.Treeview(right_col, columns=cols, show="headings", height=20)
        self.tree.heading("timestamp", text="Timestamp")
        self.tree.heading("id", text="ID")
        self.tree.heading("name", text="Name")
        self.tree.heading("section", text="Section")
        self.tree.heading("action", text="Action")
        self.tree.column("timestamp", width=180)
        self.tree.column("id", width=90, anchor=tk.CENTER)
        self.tree.column("name", width=220)
        self.tree.column("section", width=140, anchor=tk.CENTER)
        self.tree.column("action", width=80, anchor=tk.CENTER)
        self.tree.pack(fill=tk.BOTH, expand=True)

        # Serial connection status label under the treeview
        self.serial_status_var = tk.StringVar(value="Arduino: Unknown")
        status_lbl = ttk.Label(right_col, textvariable=self.serial_status_var, padding=(4,6))
        status_lbl.pack(fill=tk.X)

        self.refresh_logs()

    def refresh_logs(self):
        for r in self.tree.get_children():
            self.tree.delete(r)
        logs = self.db.get("logs", [])
        for entry in sorted(logs, key=lambda e: e.get("timestamp", ""), reverse=True):
            self.tree.insert(
                "",
                tk.END,
                values=(
                    entry.get("timestamp", ""),
                    entry.get("id", ""),
                    entry.get("name", ""),
                    entry.get("Section", "") or entry.get("section", "") or entry.get("Section", ""),
                    entry.get("action", ""),
                ),
            )

    def filter_logs(self, query: str):
        """Filter the main treeview by ID, name, section, or action."""
        q = (query or "").strip().lower()
        if not q:
            return self.refresh_logs()
        for r in self.tree.get_children():
            self.tree.delete(r)
        logs = self.db.get("logs", [])
        matched = []
        for entry in logs:
            id_ = str(entry.get("id", ""))
            name = str(entry.get("name", ""))
            section = str(entry.get("Section", "") or entry.get("section", "") or entry.get("Section", ""))
            action = str(entry.get("action", ""))
            if q in id_.lower() or q in name.lower() or q in section.lower() or q in action.lower():
                matched.append(entry)
        for entry in sorted(matched, key=lambda e: e.get("timestamp", ""), reverse=True):
            self.tree.insert(
                "",
                tk.END,
                values=(
                    entry.get("timestamp", ""),
                    entry.get("id", ""),
                    entry.get("name", ""),
                    entry.get("Section", "") or entry.get("section", "") or entry.get("Section", ""),
                    entry.get("action", ""),
                ),
            )

    def _poll_serial(self):
        # read serial lines and update pending UID/state
        try:
            if self.serial and self.serial.in_waiting:
                line = self.serial.readline().decode().strip()
                if line.startswith("UID:"):
                    uid = line.split(":",1)[1]
                    self.pending_uid = uid
                    if self.waiting_for_uid:
                        self.waiting_for_uid = False
                        # Always update the UID entry if present
                        if hasattr(self, '_current_uid_entry') and self._current_uid_entry:
                            self._current_uid_entry.delete(0, tk.END)
                            self._current_uid_entry.insert(0, uid)
                        # Also update any registration UID field if present
                        if hasattr(self, 'reg_uid_entry') and self.reg_uid_entry:
                            self.reg_uid_entry.delete(0, tk.END)
                            self.reg_uid_entry.insert(0, uid)
                    else:
                        # Check if UID is already recorded in student database
                        matching_sid = None
                        for sid, student in self.db.get("students", {}).items():
                            if student.get("uid", "").strip().upper() == uid.strip().upper():
                                matching_sid = sid
                                break
                        # If UID is recorded, toggle the student's IN/OUT status
                        if matching_sid:
                            student = self.db.get("students", {}).get(matching_sid)
                            if student:
                                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                prev = student.get("last_action", "OUT")
                                new_action = "IN" if prev != "IN" else "OUT"
                                student["last_action"] = new_action
                                student["last_seen"] = ts
                                self.db.setdefault("students", {})[matching_sid] = student
                                # Log the action
                                self.db.setdefault("logs", []).append({
                                    "id": matching_sid,
                                    "name": student.get("name", ""),
                                    "Section": student.get("grade_section", ""),
                                    "action": new_action,
                                    "timestamp": ts
                                })
                                save_db(self.db)
                                # Update output label with name and action
                                action_text = "logged in" if new_action == "IN" else "logged out"
                                self.output_var.set(f"{student['name']} {action_text}")
                                # Send UNLOCK to Arduino
                                try:
                                    if self.serial:
                                        self.serial.write(b"UNLOCK\n")
                                        # Also send STUDENT message
                                        last_name = student.get('last_name', '')
                                        first_name = student.get('first_name', '')
                                        msg = f"STUDENT:{last_name} {first_name},{new_action}\n"
                                        self.serial.write(msg.encode('utf-8'))
                                except Exception:
                                    pass
                                # Refresh main table and all status windows
                                try:
                                    self.refresh_logs()
                                except Exception:
                                    pass
                                # Refresh all open status windows if any
                                if hasattr(self, '_status_windows'):
                                    for win, tv in self._status_windows:
                                        self._refresh_students_status_tree(tv)
                        else:
                            # UID not found in database — send FAIL to Arduino
                            self.output_var.set("Access denied - UID not recognized")
                            try:
                                if self.serial:
                                    self.serial.write(b"FAIL\n")
                            except Exception:
                                pass
                # could handle other serial commands here
        except Exception:
            pass
        self.root.after(50, self._poll_serial)

    def send_lock(self):
        try:
            if getattr(self, 'serial', None):
                self.serial.write(b"UNLOCK\n")
                self.output_var.set("Sent LOCK to Arduino")
                try: self.update_serial_status()
                except Exception: pass
            else:
                self.output_var.set("No serial connected to send LOCK")
                try: self.update_serial_status()
                except Exception: pass
        except Exception:
            self.output_var.set("Failed to send LOCK")
            try: self.update_serial_status()
            except Exception: pass

    def send_unlock(self):
        try:
            if getattr(self, 'serial', None):
                self.serial.write(b"LOCK\n")
                self.output_var.set("Sent UNLOCK to Arduino")
                try: self.update_serial_status()
                except Exception: pass
            else:
                self.output_var.set("No serial connected to send UNLOCK")
                try: self.update_serial_status()
                except Exception: pass
        except Exception:
            self.output_var.set("Failed to send UNLOCK")
            try: self.update_serial_status()
            except Exception: pass

    def update_serial_status(self):
        """Refresh the serial status label text based on current connection."""
        ser = getattr(self, 'serial', None)
        if ser:
            port = getattr(ser, 'port', None) or getattr(ser, 'name', None) or ''
            try:
                text = f"Arduino: Connected ({port})" if port else "Arduino: Connected"
            except Exception:
                text = "Arduino: Connected"
        else:
            text = "Arduino: Not connected"
        try:
            self.serial_status_var.set(text)
        except Exception:
            pass

    def _monitor_serial(self):
        """Background monitor: attempts to auto-open serial when disconnected,
        and detects disconnection when serial operations fail. Runs every second."""
        try:
            if not getattr(self, 'serial', None):
                try:
                    import serial
                    ser = auto_open_serial(serial)
                    if ser:
                        self.serial = ser
                        # start polling loop if not active
                        if not getattr(self, '_polling_active', False):
                            self._polling_active = True
                            self.root.after(50, self._poll_serial)
                        try:
                            self.update_serial_status()
                        except Exception:
                            pass
                except Exception:
                    # still not connected
                    pass
            else:
                # quick health check: accessing in_waiting will raise if port gone
                try:
                    _ = self.serial.in_waiting
                except Exception:
                    try:
                        self.serial.close()
                    except Exception:
                        pass
                    self.serial = None
                    self._polling_active = False
                    try:
                        self.update_serial_status()
                    except Exception:
                        pass
        except Exception:
            pass
        # reschedule
        try:
            self.root.after(1000, self._monitor_serial)
        except Exception:
            pass

    def clear_selection(self):
        self.id_entry.delete(0, tk.END)
        self.output_var.set("Result will appear here")

    def lookup_student(self):
        sid = self.id_entry.get().strip()
        if not sid:
            messagebox.showwarning("Input Required", "Please enter a 6-digit ID.")
            return
        if not sid.isdigit() or len(sid) != 6:
            messagebox.showerror("Invalid ID", "ID must be exactly 6 digits.")
            return
        students = self.db.get("students", {})
        student = students.get(sid)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if student:
            # Toggle IN/OUT status
            prev = student.get("last_action", "OUT")
            new_action = "IN" if prev != "IN" else "OUT"
            student["last_action"] = new_action
            student["last_seen"] = ts
            self.db.setdefault("students", {})[sid] = student
            # Append to logs
            self.db.setdefault("logs", []).append({
                "id": sid,
                "name": student.get("name", ""),
                "Section": student.get("grade_section", ""),
                "action": new_action,
                "timestamp": ts
            })
            save_db(self.db)
            # notify Arduino (if connected) about the student and action
            try:
                if getattr(self, 'serial', None):
                    # send STUDENT:<id>,<action> and UID:<uid> if available
                    msg = f"STUDENT:{sid},{new_action}\n"
                    self.serial.write(msg.encode('utf-8'))
                    uidval = student.get('uid') or ''
                    if uidval:
                        self.serial.write(f"UID:{uidval}\n".encode('utf-8'))
            except Exception:
                pass
            self.refresh_logs()
            self.output_var.set(f"{student['name']} — {student['grade_section']} — {new_action} — {ts}")
        else:
            # Not found: still record attempted lookup if desired, here we just show message and a log entry
            self.db.setdefault("logs", []).append({
                "id": sid,
                "name": "",
                "action": "NOT_FOUND",
                "timestamp": ts
            })
            save_db(self.db)
            self.output_var.set(f"Student with ID {sid} not found — {ts}")

    def open_admin_login(self):
        pw = simpledialog.askstring("Admin Login", "Enter admin password:", show="*")
        if pw is None:
            return
        if hash_password(pw) == self.db.get("admin_password_hash"):
            self.open_admin_panel()
        else:
            messagebox.showerror("Login Failed", "Incorrect password.")

    def open_admin_panel(self):
        panel = tk.Toplevel(self.root)
        panel.title("Admin Panel")
        panel.grab_set()
        main_frm = ttk.Frame(panel, padding=10)
        main_frm.pack(fill=tk.BOTH, expand=True)

        # Left: student list
        list_frm = ttk.Frame(main_frm)
        list_frm.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(list_frm, text="Students", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        cols = ("id", "uid", "name", "last_action")
        tv = ttk.Treeview(list_frm, columns=cols, show="tree headings", height=12)
        tv.heading("#0", text="Section")
        tv.heading("id", text="ID")
        tv.heading("uid", text="UID")
        tv.heading("name", text="Name")
        tv.heading("last_action", text="Status")
        tv.column("#0", width=120)
        tv.column("id", width=90, anchor=tk.CENTER)
        tv.column("uid", width=140, anchor=tk.CENTER)
        tv.column("name", width=180)
        tv.column("last_action", width=80, anchor=tk.CENTER)
        tv.pack(fill=tk.BOTH, expand=True)
        list_frm.rowconfigure(0, weight=1)

        # Right: form for add/edit
        form_frm = ttk.Frame(main_frm)
        form_frm.grid(row=0, column=1, sticky="n", padx=(8, 0))
        main_frm.columnconfigure(0, weight=1)

        ttk.Label(form_frm, text="Last Name:").grid(row=0, column=0, sticky=tk.E)
        last_e = ttk.Entry(form_frm, width=15)
        last_e.grid(row=0, column=1, pady=2, sticky=tk.W)

        ttk.Label(form_frm, text="First Name:").grid(row=1, column=0, sticky=tk.E)
        first_e = ttk.Entry(form_frm, width=15)
        first_e.grid(row=1, column=1, pady=2, sticky=tk.W)

        ttk.Label(form_frm, text="Middle Name:").grid(row=2, column=0, sticky=tk.E)
        middle_e = ttk.Entry(form_frm, width=15)
        middle_e.grid(row=2, column=1, pady=2, sticky=tk.W)

        ttk.Label(form_frm, text="6-digit ID:").grid(row=3, column=0, sticky=tk.E)
        id_e = ttk.Entry(form_frm, width=15, state="readonly")
        id_e.grid(row=3, column=1, pady=2, sticky=tk.W)

        ttk.Label(form_frm, text="RFID UID:").grid(row=4, column=0, sticky=tk.E)
        uid_e = ttk.Entry(form_frm, width=25)
        uid_e.grid(row=4, column=1, pady=2, sticky=tk.W)
        scan_btn = ttk.Button(form_frm, text="Scan Card")
        scan_btn.grid(row=4, column=2, padx=(4,0), pady=2)
        # clicking will wait for next UID from serial
        def on_scan():
            self.waiting_for_uid = True
            uid_e.delete(0, tk.END)
            messagebox.showinfo("Scan", "Please present a card to reader...")
        scan_btn.config(command=on_scan)

        ttk.Label(form_frm, text="Grade - Section:").grid(row=5, column=0, sticky=tk.E)
        grade_options = ["IC1MA", "IC2DA", "BM1MA", "BM2DA", "HU1MA", "HU2DA", "FACULTY", "STAFF"]
        grade_e = ttk.Combobox(form_frm, values=grade_options, width=20, state="readonly")
        grade_e.grid(row=5, column=1, pady=2, sticky=tk.W)

        # Buttons
        add_btn = ttk.Button(form_frm, text="Add")
        add_btn.grid(row=6, column=0, columnspan=2, pady=(8, 4), sticky="ew")

        update_btn = ttk.Button(form_frm, text="Update")
        update_btn.grid(row=7, column=0, columnspan=2, pady=(4, 4), sticky="ew")

        delete_btn = ttk.Button(form_frm, text="Delete")
        delete_btn.grid(row=8, column=0, columnspan=2, pady=(4, 8), sticky="ew")
        ttk.Label(form_frm, text="Change Admin Password", font=("Arial", 10, "bold")).grid(row=9, column=0, columnspan=2, pady=(0, 6))
        ttk.Label(form_frm, text="New password:").grid(row=10, column=0, sticky=tk.E)
        newpw_e = ttk.Entry(form_frm, show="*", width=20)
        newpw_e.grid(row=10, column=1, sticky=tk.W)

        ch_btn = ttk.Button(form_frm, text="Change Password")
        ch_btn.grid(row=11, column=0, columnspan=2, pady=(6, 0), sticky="ew")

        # Helpers
        def populate_tree():
            for r in tv.get_children():
                tv.delete(r)
            students = self.db.get("students", {})
            # Group students by section
            sections = {}
            for sid, s in students.items():
                section = s.get("grade_section", "No Section")
                if section not in sections:
                    sections[section] = []
                sections[section].append((sid, s))
            for section, studs in sorted(sections.items()):
                parent = tv.insert("", tk.END, text=section, values=("", "", "", ""))
                for sid, s in sorted(studs):
                    tv.insert(parent, tk.END, iid=sid, text="", values=(sid, s.get("uid", ""), s.get("name", ""), s.get("last_action", "")))
        # keep reference to uid entry so poller can update it
        self._current_uid_entry = uid_e

        def clear_form():
            last_e.delete(0, tk.END)
            first_e.delete(0, tk.END)
            middle_e.delete(0, tk.END)
            uid_e.delete(0, tk.END)
            id_e.config(state="normal")
            id_e.delete(0, tk.END)
            # Auto-generate and display next ID
            existing_ids = [int(sid) for sid in self.db.get("students", {}).keys() if sid.isdigit()]
            next_id = max(existing_ids) + 1 if existing_ids else 1
            id_e.insert(0, str(next_id).zfill(6))
            id_e.config(state="readonly")
            grade_e.set("")
            tv.selection_remove(tv.selection())

        def on_select(event):
            sel = tv.selection()
            if not sel:
                return
            item_values = tv.item(sel[0], 'values')
            if not item_values or not item_values[0]:
                return  # Selected a section, not a student
            sid = sel[0]
            s = self.db.get("students", {}).get(sid, {})
            last_e.delete(0, tk.END); last_e.insert(0, s.get("last_name", ""))
            first_e.delete(0, tk.END); first_e.insert(0, s.get("first_name", ""))
            middle_e.delete(0, tk.END); middle_e.insert(0, s.get("middle_name", ""))
            uid_e.delete(0, tk.END); uid_e.insert(0, s.get("uid", ""))
            id_e.config(state="normal")
            id_e.delete(0, tk.END); id_e.insert(0, sid)
            id_e.config(state="readonly")
            grade_e.set(s.get("grade_section", ""))

        tv.bind("<<TreeviewSelect>>", on_select)

        def add_student():
            last = last_e.get().strip()
            first = first_e.get().strip()
            middle = middle_e.get().strip()
            uidval = uid_e.get().strip()
            grade = grade_e.get().strip()
            if not last or not first:
                messagebox.showerror("Missing Data", "Last Name and First Name are required.")
                return
            name = f"{last}, {first} {middle}".strip()
            # Auto-generate next ID
            existing_ids = [int(sid) for sid in self.db.get("students", {}).keys() if sid.isdigit()]
            next_id = max(existing_ids) + 1 if existing_ids else 1
            sid = str(next_id).zfill(6)
            self.db.setdefault("students", {})[sid] = {"last_name": last, "first_name": first, "middle_name": middle, "name": name, "uid": uidval, "grade_section": grade, "last_seen": "", "last_action": ""}
            save_db(self.db)
            populate_tree()
            # update main table as well
            try:
                self.refresh_logs()
            except Exception:
                pass
            clear_form()
            messagebox.showinfo("Added", f"Student {name} added with ID {sid}.")

        def update_student():
            sel = tv.selection()
            if not sel:
                messagebox.showerror("No selection", "Select a student from the list to update (or use Add Student).")
                return
            orig_sid = sel[0]
            last = last_e.get().strip()
            first = first_e.get().strip()
            middle = middle_e.get().strip()
            uidval = uid_e.get().strip()
            grade = grade_e.get().strip()
            if not last or not first:
                messagebox.showerror("Missing Data", "Last Name and First Name are required.")
                return
            name = f"{last}, {first} {middle}".strip()
            students = self.db.setdefault("students", {})
            # preserve last_seen/last_action
            entry = students.get(orig_sid, {})
            entry.update({"last_name": last, "first_name": first, "middle_name": middle, "name": name, "uid": uidval, "grade_section": grade})
            students[orig_sid] = entry
            save_db(self.db)
            populate_tree()
            # update main table as well
            try:
                self.refresh_logs()
            except Exception:
                pass
            # reselect updated row
            try:
                tv.selection_set(orig_sid)
                tv.see(orig_sid)
            except Exception:
                pass
            messagebox.showinfo("Updated", f"Student {name} updated.")

        def delete_student():
            sel = tv.selection()
            if not sel:
                messagebox.showerror("No selection", "Select a student to delete.")
                return
            sid = sel[0]
            name = self.db.get("students", {}).get(sid, {}).get("name", sid)
            if not messagebox.askyesno("Confirm Delete", f"Delete student {name} (ID {sid})? This cannot be undone."):
                return
            self.db.get("students", {}).pop(sid, None)
            save_db(self.db)
            populate_tree()
            # update main table as well
            try:
                self.refresh_logs()
            except Exception:
                pass
            clear_form()
            messagebox.showinfo("Deleted", f"Student {name} deleted.")

        def change_password():
            npw = newpw_e.get().strip()
            if not npw:
                messagebox.showerror("Error", "Password cannot be empty.")
                return
            self.db["admin_password_hash"] = hash_password(npw)
            save_db(self.db)
            messagebox.showinfo("Success", "Admin password changed.")
            newpw_e.delete(0, tk.END)

        # wire buttons
        add_btn.config(command=add_student)
        update_btn.config(command=update_student)
        delete_btn.config(command=delete_student)
        ch_btn.config(command=change_password)

        populate_tree()
        clear_form()
        panel.transient(self.root)
        panel.wait_window(panel)

    def open_logs_window(self):
        logs = self.db.get("logs", [])
        win = tk.Toplevel(self.root)
        win.title("Logs")
        win.geometry("800x400")
        frm = ttk.Frame(win, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        cols = ("timestamp", "id", "name", "section", "action")
        tv = ttk.Treeview(frm, columns=cols, show="headings", height=15)
        tv.heading("timestamp", text="Timestamp")
        tv.heading("id", text="ID")
        tv.heading("name", text="Name")
        tv.heading("section", text="Section")
        tv.heading("action", text="Action")
        tv.column("timestamp", width=180)
        tv.column("id", width=90, anchor=tk.CENTER)
        tv.column("name", width=220)
        tv.column("section", width=140, anchor=tk.CENTER)
        tv.column("action", width=80, anchor=tk.CENTER)
        tv.pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        for entry in sorted(logs, key=lambda e: e.get("timestamp", ""), reverse=True):
            tv.insert(
                "",
                tk.END,
                values=(
                    entry.get("timestamp", ""),
                    entry.get("id", ""),
                    entry.get("name", ""),
                    entry.get("Section", "") or entry.get("section", "") or entry.get("Section", ""),
                    entry.get("action", ""),
                ),
            )

        btn_frame = ttk.Frame(frm)
        btn_frame.pack(fill=tk.X, pady=(6, 0))
        clear_btn = ttk.Button(btn_frame, text="Clear Logs", command=lambda: self.clear_logs(tv, win))
        clear_btn.pack(side=tk.LEFT, padx=4)


        win.transient(self.root)
        win.grab_set()
        win.wait_window(win)

    def clear_logs(self, tv, win):
        if messagebox.askyesno("Confirm", "Clear all logs? This cannot be undone."):
            self.db["logs"] = []
            save_db(self.db)
            for r in tv.get_children():
                tv.delete(r)
            self.refresh_logs()
            messagebox.showinfo("Cleared", "Logs cleared.")

    def export_logs_csv(self):
        logs = self.db.get("logs", [])
        if not logs:
            messagebox.showinfo("No logs", "There are no logs to export.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")], title="Save logs as CSV")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("timestamp,id,name,section,action\n")
                for e in logs:
                    # simple CSV escaping: replace quotes with double quotes and wrap fields containing commas/quotes/newlines
                    def esc(v):
                        v = str(v).replace('"', '""')
                        if "," in v or '"' in v or "\n" in v:
                            return f'"{v}"'
                        return v
                    section = e.get("Section", "") or e.get("section", "") or e.get("Section", "")
                    f.write(",".join([
                        esc(e.get("timestamp", "")),
                        esc(e.get("id", "")),
                        esc(e.get("name", "")),
                        esc(section),
                        esc(e.get("action", ""))
                    ]) + "\n")
            messagebox.showinfo("Exported", f"Logs exported to {path}")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to export logs: {exc}")

    def open_students_window(self):
        students = self.db.get("students", {})
        win = tk.Toplevel(self.root)
        win.title("Students Status")
        win.geometry("800x400")
        frm = ttk.Frame(win, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        cols = ("id", "name", "last_action", "last_seen")
        tv = ttk.Treeview(frm, columns=cols, show="tree headings", height=15)
        tv.heading("#0", text="Section")
        tv.heading("id", text="ID")
        tv.heading("name", text="Name")
        tv.heading("last_action", text="Status")
        tv.heading("last_seen", text="Last Seen")
        tv.column("#0", width=140)
        tv.column("id", width=90, anchor=tk.CENTER)
        tv.column("name", width=220)
        tv.column("last_action", width=80, anchor=tk.CENTER)
        tv.column("last_seen", width=180)
        tv.pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        def refresh_tree():
            self._refresh_students_status_tree(tv)

        refresh_btn = ttk.Button(frm, text="Refresh", command=refresh_tree)
        refresh_btn.pack(pady=(4,0))

        # Track open status windows for live refresh
        if not hasattr(self, '_status_windows'):
            self._status_windows = []
        self._status_windows.append((win, tv))
        win.protocol("WM_DELETE_WINDOW", lambda: (self._status_windows.remove((win, tv)), win.destroy()))

        refresh_tree()
        win.transient(self.root)
        win.grab_set()
        win.wait_window(win)

    def _refresh_students_status_tree(self, tv):
        students = self.db.get("students", {})
        for r in tv.get_children():
            tv.delete(r)
        # Group students by section
        sections = {}
        for sid, s in students.items():
            section = s.get("grade_section", "No Section")
            if section not in sections:
                sections[section] = []
            sections[section].append((sid, s))
        for section, studs in sorted(sections.items()):
            parent = tv.insert("", tk.END, text=section, values=("", "", "", ""))
            for sid, s in sorted(studs):
                tv.insert(parent, tk.END, text="", values=(sid, s.get("name", ""), s.get("last_action", ""), s.get("last_seen", "")))


def main():
    root = tk.Tk()
    app = StudentApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
