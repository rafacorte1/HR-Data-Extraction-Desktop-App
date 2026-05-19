# -*- coding: utf-8 -*-
"""
GUI app (CustomTkinter) for batch extraction of employee identity attributes
from a web-based HR/Identity Management system.

Features:
- Add multiple names to a queue and execute sequential scraping
- One tab per user with the extracted Attribute/Value table
- Pause an in-flight batch and export partial results
- Restart (clear everything) to reset the app
- Export selected tab to CSV or all tabs to Excel (one sheet per user)
- Real-time indicator of search and total elapsed time
"""

import threading
import time
from time import sleep
from typing import Dict, List, Optional

import pandas as pd

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import customtkinter as ctk

from src.config import DEFAULT_TIMEOUT
from src.scraper import init_driver, scrape_user
from src.utils import format_hms


class HRExtractorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.title("HR Data Extractor — Batch Identity Attributes")
        self.geometry("1200x750")
        self.minsize(1000, 650)

        # State
        self._dfs_by_user: Dict[str, pd.DataFrame] = {}
        self._driver = None
        self._running_thread: Optional[threading.Thread] = None
        self._pause_requested = False
        self._run_started_at: Optional[float] = None
        self._search_done_at: Optional[float] = None

        # Layout
        self._build_top_controls()
        self._build_name_list_area()
        self._build_progress_area()
        self._build_tabs_area()
        self._build_bottom_buttons()

        self.bind("<Return>", lambda _: self.on_add_name())

    # ---------- UI builders ----------
    def _build_top_controls(self):
        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.pack(fill="x", padx=16, pady=(12, 8))
        self.top_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.top_frame, text="Full Name:").grid(
            row=0, column=0, padx=(8, 6), pady=6, sticky="w"
        )
        self.ent_name = ctk.CTkEntry(self.top_frame, placeholder_text="e.g., Jane Doe")
        self.ent_name.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        self.btn_add_name = ctk.CTkButton(
            self.top_frame, text="Add to list", command=self.on_add_name
        )
        self.btn_add_name.grid(row=0, column=2, padx=12, pady=6, sticky="w")

        self.var_headless = tk.BooleanVar(value=False)
        self.chk_headless = ctk.CTkCheckBox(
            self.top_frame, text="Run headless", variable=self.var_headless
        )
        self.chk_headless.grid(row=0, column=3, padx=12, pady=6, sticky="w")

        ctk.CTkLabel(self.top_frame, text="Timeout (s):").grid(
            row=0, column=4, padx=(22, 6), pady=6, sticky="e"
        )
        self.var_timeout = tk.IntVar(value=DEFAULT_TIMEOUT)

        def _on_timeout_change(value):
            v = int(round(float(value) / 5.0) * 5)
            v = max(10, min(90, v))
            self.var_timeout.set(v)
            self.lbl_timeout_value.configure(text=str(v))

        self.sld_timeout = ctk.CTkSlider(
            self.top_frame,
            from_=10,
            to=90,
            command=_on_timeout_change,
            number_of_steps=16,
        )
        self.sld_timeout.set(DEFAULT_TIMEOUT)
        self.sld_timeout.grid(row=0, column=5, padx=6, pady=6, sticky="ew")
        self.lbl_timeout_value = ctk.CTkLabel(
            self.top_frame, text=str(self.var_timeout.get())
        )
        self.lbl_timeout_value.grid(row=0, column=6, padx=(6, 8), pady=6, sticky="w")

        self.btn_execute = ctk.CTkButton(
            self.top_frame,
            text="Execute (all names in list)",
            command=self.on_execute,
        )
        self.btn_execute.grid(row=2, column=1, padx=(6, 4), pady=(10, 6), sticky="w")

        self.btn_pause = ctk.CTkButton(
            self.top_frame,
            text="Pause search",
            fg_color="#d97706",
            hover_color="#b45309",
            state="disabled",
            command=self.on_pause,
        )
        self.btn_pause.grid(row=2, column=2, padx=4, pady=(10, 6), sticky="w")

        self.btn_clear_results = ctk.CTkButton(
            self.top_frame,
            text="Clear results",
            fg_color="#6b7280",
            hover_color="#4b5563",
            command=self.on_clear_results,
        )
        self.btn_clear_results.grid(row=2, column=3, padx=4, pady=(10, 6), sticky="w")

        self.btn_reset_all = ctk.CTkButton(
            self.top_frame,
            text="Restart (clear everything)",
            fg_color="#ef4444",
            hover_color="#dc2626",
            command=self.on_reset_all,
        )
        self.btn_reset_all.grid(row=2, column=4, padx=8, pady=(10, 6), sticky="w")

    def _build_name_list_area(self):
        self.list_frame = ctk.CTkFrame(self)
        self.list_frame.pack(fill="x", padx=16, pady=(0, 8))
        self.list_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.list_frame, text="Names queued for search").grid(
            row=0, column=0, padx=8, pady=(8, 4), sticky="w"
        )

        self.lst_names = tk.Listbox(
            self.list_frame, height=6, selectmode=tk.EXTENDED
        )
        self.lst_names.grid(row=1, column=0, columnspan=4, sticky="ew", padx=8, pady=6)

        self.btn_remove_selected = ctk.CTkButton(
            self.list_frame,
            text="Remove selected",
            command=self.on_remove_selected,
        )
        self.btn_remove_selected.grid(row=2, column=0, padx=8, pady=(4, 8), sticky="w")

        self.btn_clear_list = ctk.CTkButton(
            self.list_frame,
            text="Clear list",
            fg_color="#6b7280",
            hover_color="#4b5563",
            command=self.on_clear_list,
        )
        self.btn_clear_list.grid(row=2, column=1, padx=8, pady=(4, 8), sticky="w")

    def _build_progress_area(self):
        self.progress_frame = ctk.CTkFrame(self)
        self.progress_frame.pack(fill="x", padx=16, pady=(0, 8))

        self.lbl_status = ctk.CTkLabel(self.progress_frame, text="Ready.", anchor="w")
        self.lbl_status.pack(side="left", padx=8, pady=8)

        self.progressbar = ctk.CTkProgressBar(
            self.progress_frame, mode="indeterminate", width=250
        )
        self.progressbar.set(0)

    def _build_tabs_area(self):
        self.tabs_frame = ctk.CTkFrame(self)
        self.tabs_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        self.notebook = ttk.Notebook(self.tabs_frame)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=6)

    def _build_bottom_buttons(self):
        self.bottom_frame = ctk.CTkFrame(self)
        self.bottom_frame.pack(fill="x", padx=16, pady=(0, 12))

        self.btn_save_csv = ctk.CTkButton(
            self.bottom_frame,
            text="Export CSV — selected tab",
            state="disabled",
            command=self.on_save_csv_current_tab,
        )
        self.btn_save_csv.pack(side="left", padx=(8, 4), pady=8)

        self.btn_save_excel = ctk.CTkButton(
            self.bottom_frame,
            text="Export Excel (all tabs)",
            state="disabled",
            command=self.on_save_excel_all,
        )
        self.btn_save_excel.pack(side="left", padx=12, pady=8)

        self.lbl_elapsed = ctk.CTkLabel(self.bottom_frame, text="")
        self.lbl_elapsed.pack(side="right", padx=8, pady=8)

    # ---------- UI helpers ----------
    def _create_tree(self, parent) -> ttk.Treeview:
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)

        xscroll = ttk.Scrollbar(container, orient="horizontal")
        yscroll = ttk.Scrollbar(container, orient="vertical")
        tree = ttk.Treeview(
            container,
            columns=(),
            show="headings",
            xscrollcommand=xscroll.set,
            yscrollcommand=yscroll.set,
        )
        xscroll.config(command=tree.xview)
        yscroll.config(command=tree.yview)

        tree.grid(row=0, column=0, sticky="nsew")
        xscroll.grid(row=1, column=0, sticky="ew")
        yscroll.grid(row=0, column=1, sticky="ns")

        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        return tree

    def _df_to_tree(self, tree: ttk.Treeview, df: Optional[pd.DataFrame]):
        for col in tree["columns"]:
            tree.heading(col, text="")
        tree.delete(*tree.get_children())

        if df is None or df.empty:
            tree["columns"] = ("info",)
            tree.heading("info", text="(no data)")
            return

        cols = list(df.columns)
        tree["columns"] = cols

        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=max(120, int(900 / max(1, len(cols)))))

        preview_rows = min(500, len(df))
        for _, row in df.head(preview_rows).iterrows():
            values = [str(x) if x is not None else "" for x in row.tolist()]
            tree.insert("", "end", values=values)

    def _set_status(self, text: str):
        self.lbl_status.configure(text=text)
        self.update_idletasks()

    def _disable_controls(self):
        self.btn_execute.configure(state="disabled")
        self.btn_clear_results.configure(state="disabled")
        self.chk_headless.configure(state="disabled")
        self.ent_name.configure(state="disabled")
        self.btn_add_name.configure(state="disabled")
        self.btn_remove_selected.configure(state="disabled")
        self.btn_clear_list.configure(state="disabled")
        self.sld_timeout.configure(state="disabled")
        self.lst_names.configure(state="disabled")
        self.btn_pause.configure(state="normal")
        self.btn_reset_all.configure(state="disabled")

    def _enable_controls(self):
        self.btn_execute.configure(state="normal")
        self.btn_clear_results.configure(state="normal")
        self.chk_headless.configure(state="normal")
        self.ent_name.configure(state="normal")
        self.btn_add_name.configure(state="normal")
        self.btn_remove_selected.configure(state="normal")
        self.btn_clear_list.configure(state="normal")
        self.sld_timeout.configure(state="normal")
        self.lst_names.configure(state="normal")
        self.btn_pause.configure(state="disabled")
        self.btn_reset_all.configure(state="normal")

    def _enable_downloads(self, enable: bool):
        state = "normal" if enable else "disabled"
        self.btn_save_excel.configure(state=state)
        self.btn_save_csv.configure(state=state)

    # ---------- List callbacks ----------
    def on_add_name(self):
        name = self.ent_name.get().strip()
        if not name:
            messagebox.showerror("Validation", "Please enter a full name.")
            return
        existing = set(self.lst_names.get(0, tk.END))
        if name in existing:
            messagebox.showinfo("List", f"'{name}' is already on the list.")
            return
        self.lst_names.insert(tk.END, name)
        self.ent_name.delete(0, tk.END)

    def on_remove_selected(self):
        sel = list(self.lst_names.curselection())
        if not sel:
            messagebox.showinfo("List", "Select one or more names to remove.")
            return
        for idx in reversed(sel):
            self.lst_names.delete(idx)

    def on_clear_list(self):
        self.lst_names.delete(0, tk.END)

    # ---------- Main callbacks ----------
    def on_pause(self):
        if self._pause_requested:
            return
        self._pause_requested = True
        self.btn_pause.configure(state="disabled")
        self._set_status(
            "Pause requested. Finishing the current user and preparing partial export..."
        )

    def on_execute(self):
        names: List[str] = list(self.lst_names.get(0, tk.END))
        fallback = self.ent_name.get().strip()
        if not names and fallback:
            names = [fallback]
        if not names:
            messagebox.showerror(
                "Validation", "Add at least one name to the list."
            )
            return

        headless = self.var_headless.get()
        timeout = int(self.var_timeout.get())
        self._pause_requested = False

        self._run_started_at = time.time()
        self._search_done_at = None
        self.lbl_elapsed.configure(text="")

        self._disable_controls()
        self._enable_downloads(False)
        self.progressbar.pack(side="right", padx=12, pady=8)
        self.progressbar.start()
        self._set_status(f"Running {len(names)} search(es)...")

        def _run():
            driver = None
            try:
                self._set_status("Initializing browser...")
                driver = init_driver(headless=headless)
                self._driver = driver

                results: Dict[str, pd.DataFrame] = {}
                total = len(names)
                for i, name in enumerate(names, start=1):
                    if self._pause_requested:
                        break
                    try:
                        self._set_status(f"[{i}/{total}] Searching: {name}")
                        df = scrape_user(driver, name, timeout=timeout)
                        results[name] = df
                    except Exception:
                        results[name] = pd.DataFrame()
                    if self._pause_requested:
                        break
                    sleep(0.2)

                self._search_done_at = time.time()
                self.after(0, lambda: self._on_scrape_done(results))
            except Exception as e:
                self.after(0, lambda: self._on_scrape_error(e))
            finally:
                try:
                    if driver:
                        driver.quit()
                except Exception:
                    pass
                self._driver = None

        self._running_thread = threading.Thread(target=_run, daemon=True)
        self._running_thread.start()

    def _on_scrape_done(self, results: Dict[str, pd.DataFrame]):
        self.progressbar.stop()
        self.progressbar.pack_forget()

        self._dfs_by_user = results or {}

        for _ in range(len(self.notebook.tabs())):
            self.notebook.forget(0)

        any_data = False
        for name, df in self._dfs_by_user.items():
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text=f"Attributes — {name}")
            tree = self._create_tree(tab)
            self._df_to_tree(tree, df if df is not None else pd.DataFrame())
            if df is not None and not df.empty:
                any_data = True

        if self._run_started_at and self._search_done_at:
            search_sec = self._search_done_at - self._run_started_at
            self.lbl_elapsed.configure(
                text=f"⏱ Search: {format_hms(search_sec)} (waiting to export)"
            )

        if not self._dfs_by_user:
            self._set_status("No results returned.")
            self._enable_controls()
            self._enable_downloads(False)
            return

        if self._pause_requested:
            self._set_status(
                "Search paused. Export the partial results to Excel."
            )
        else:
            self._set_status(
                "Search completed successfully."
                if any_data
                else "Search completed. No attributes found for the provided names."
            )

        self._enable_controls()
        self._enable_downloads(True)

        if self._pause_requested:
            self._pause_requested = False
            self.on_save_excel_all()

    def _on_scrape_error(self, exc: Exception):
        self.progressbar.stop()
        self.progressbar.pack_forget()
        self._enable_controls()
        self._enable_downloads(False)
        self._set_status("Execution failed.")
        messagebox.showerror("Error", f"Execution failed: {exc}")

    def on_clear_results(self):
        self._dfs_by_user = {}
        for _ in range(len(self.notebook.tabs())):
            self.notebook.forget(0)
        self._enable_downloads(False)
        self._set_status("Ready.")

    def on_reset_all(self):
        self._pause_requested = True

        try:
            self.progressbar.stop()
            self.progressbar.pack_forget()
        except Exception:
            pass

        try:
            if self._driver:
                self._driver.quit()
        except Exception:
            pass
        finally:
            self._driver = None

        self._running_thread = None
        self._dfs_by_user = {}
        for _ in range(len(self.notebook.tabs())):
            self.notebook.forget(0)

        try:
            self.lst_names.delete(0, tk.END)
        except Exception:
            pass
        self.ent_name.delete(0, tk.END)

        try:
            self.var_headless.set(False)
            self.var_timeout.set(DEFAULT_TIMEOUT)
            self.sld_timeout.set(DEFAULT_TIMEOUT)
        except Exception:
            pass

        self._run_started_at = None
        self._search_done_at = None
        self.lbl_elapsed.configure(text="")

        self._enable_downloads(False)
        self._enable_controls()
        self._set_status("Application restarted. Ready for new execution.")

    # ---------- Exports ----------
    def on_save_csv_current_tab(self):
        if not self.notebook.tabs():
            messagebox.showwarning("Export CSV", "No tab selected.")
            return

        idx = self.notebook.index(self.notebook.select())
        tab_text = self.notebook.tab(idx, "text")
        try:
            user_name = tab_text.split("—", 1)[1].strip()
        except Exception:
            user_name = tab_text.strip()

        df = self._dfs_by_user.get(user_name)
        if df is None or df.empty:
            messagebox.showwarning("Export CSV", f"No data available for {user_name}.")
            return

        default_name = f"Attributes_{user_name.replace(' ', '_')}.csv"
        file = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=default_name,
            title=f"Export CSV — {user_name}",
        )
        if not file:
            return

        try:
            df.to_csv(file, index=False, encoding="utf-8")
            messagebox.showinfo("Export CSV", f"File saved:\n{file}")
        except Exception as e:
            messagebox.showerror("Export CSV", f"Error saving CSV: {e}")

    def on_save_excel_all(self):
        if not self._dfs_by_user:
            messagebox.showwarning("Export Excel", "There is no data to export.")
            return

        export_start = time.time()
        file = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile="HR_Attributes.xlsx",
            title="Export Excel (all tabs)",
        )
        if not file:
            if self._run_started_at and self._search_done_at:
                search_sec = self._search_done_at - self._run_started_at
                self.lbl_elapsed.configure(
                    text=f"⏱ Search: {format_hms(search_sec)} (file not saved)"
                )
            return

        try:
            with pd.ExcelWriter(file, engine="openpyxl") as writer:
                for name, df in self._dfs_by_user.items():
                    sheet_name = f"User_{name}".strip()[:31].replace("/", "_")
                    (df if df is not None else pd.DataFrame()).to_excel(
                        writer, index=False, sheet_name=sheet_name
                    )
            messagebox.showinfo("Export Excel", f"File saved:\n{file}")

            export_end = time.time()
            if self._run_started_at:
                total_sec = export_end - self._run_started_at
                self.lbl_elapsed.configure(
                    text=f"⏱ Total (search + export): {format_hms(total_sec)}"
                )
        except Exception as e:
            messagebox.showerror("Export Excel", f"Error saving Excel: {e}")


if __name__ == "__main__":
    app = HRExtractorApp()
    app.mainloop()