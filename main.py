import subprocess
import threading
import queue
import shutil
import re
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from conversion_service import convert_sas_code

BASE_DIR = Path(__file__).resolve().parent
# CONVERSION_PROMPT_FILE = BASE_DIR / "conversion_prompt.md"
#
# COPILOT_CMD = (
#     shutil.which("copilot.cmd")
#     or shutil.which("copilot")
# )

# def load_conversion_prompt():
#     if not CONVERSION_PROMPT_FILE.is_file():
#         raise FileNotFoundError(
#             f"Conversion prompt not found: {CONVERSION_PROMPT_FILE}"
#         )
#
#     prompt = CONVERSION_PROMPT_FILE.read_text(encoding="utf-8")
#
#     if not prompt.strip():
#         raise ValueError("conversion_prompt.md is empty.")
#
#     return prompt


# def get_java_code(text):
#     # look for a block that starts with ```java and ends with ```
#     blocks = re.findall(r"```(?:java)?\s*\n(.*?)```", text, flags=re.DOTALL)
#     if blocks:
#         return blocks[-1].strip()   # use the last block
#     return text.strip()             # no block found, use everything


# # makes a safe Java class name from the file name
# def make_class_name(file_stem):
#     name = re.sub(r"\W", "_", file_stem)   # replace bad characters with _
#     if name[0].isdigit():
#         name = "_" + name                  # class name cannot start with a number
#     return name


class SASJavaConverter:
    def __init__(self, root):
        self.root = root
        self.root.title("SAS to Java AI Converter")
        self.root.geometry("800x600")
        self.root.minsize(700, 520)

        self.files = []
        self.events = queue.Queue()
        self.busy = False

        self.output_path = tk.StringVar()
        self.status = tk.StringVar(value="Ready")
        self.progress = tk.DoubleVar(value=0)

        self.build_ui()
        self.root.after(100, self.process_events)

    def build_ui(self):
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        ttk.Label(
            main, text="SAS to Java AI Converter",
            font=("Segoe UI", 18, "bold")
        ).pack(anchor="w")

        ttk.Label(
            main,
            text="Convert SAS programs using GitHub Copilot CLI",
        ).pack(anchor="w", pady=(2, 16))

        input_frame = ttk.LabelFrame(
            main, text="1. Select SAS input", padding=10
        )
        input_frame.pack(fill="x", pady=5)

        buttons = ttk.Frame(input_frame)
        buttons.pack(fill="x")

        ttk.Button(
            buttons, text="Select SAS Files",
            command=self.select_files
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            buttons, text="Select Folder",
            command=self.select_folder
        ).pack(side="left")

        self.file_label = ttk.Label(
            input_frame, text="No files selected"
        )
        self.file_label.pack(anchor="w", pady=(8, 0))

        output_frame = ttk.LabelFrame(
            main, text="2. Choose output folder", padding=10
        )
        output_frame.pack(fill="x", pady=10)

        ttk.Entry(
            output_frame, textvariable=self.output_path
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        ttk.Button(
            output_frame, text="Browse",
            command=self.select_output
        ).pack(side="right")

        ttk.Label(
            main, text="3. Conversion log"
        ).pack(anchor="w", pady=(8, 4))

        self.log = tk.Text(
            main, height=12, wrap="word",
            state="disabled", font=("Consolas", 9)
        )
        self.log.pack(fill="both", expand=True)

        self.progress_bar = ttk.Progressbar(
            main, variable=self.progress, maximum=100
        )
        self.progress_bar.pack(fill="x", pady=(12, 5))

        bottom = ttk.Frame(main)
        bottom.pack(fill="x")

        ttk.Label(
            bottom, textvariable=self.status
        ).pack(side="left")

        self.convert_button = ttk.Button(
            bottom, text="Convert to Java",
            command=self.start_conversion
        )
        self.convert_button.pack(side="right")

    def add_log(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def select_files(self):
        paths = filedialog.askopenfilenames(
            title="Select SAS files",
            filetypes=[("SAS files", "*.sas")]
        )
        if paths:
            self.files = [Path(p) for p in paths]
            self.update_file_label()

    def select_folder(self):
        folder = filedialog.askdirectory(
            title="Select folder containing SAS files"
        )
        if folder:
            self.files = sorted(
                Path(folder).rglob("*.sas"),
                key=lambda p: str(p).lower()
            )
            self.update_file_label()

    def update_file_label(self):
        self.file_label.config(
            text=f"{len(self.files)} SAS file(s) selected"
        )

    def select_output(self):
        folder = filedialog.askdirectory(
            title="Choose Java output folder"
        )
        if folder:
            self.output_path.set(folder)

    def start_conversion(self):
        if self.busy:
            return

        if not self.files:
            messagebox.showwarning(
                "Input required", "Please select SAS files or a folder."
            )
            return

        output = self.output_path.get().strip()
        if not output:
            messagebox.showwarning(
                "Output required", "Please choose an output folder."
            )
            return

        # if not COPILOT_CMD:
        #     messagebox.showerror(
        #         "Copilot CLI not found",
        #         "The copilot command was not found in PATH.\n"
        #         "Restart the application or check your CLI installation."
        #     )
        #     return

        output_dir = Path(output)

        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            messagebox.showerror("Output folder error", str(error))
            return

        self.busy = True
        self.convert_button.config(state="disabled")
        self.progress.set(0)
        self.add_log("Starting conversion...")
        self.status.set("Converting...")

        worker = threading.Thread(
            target=self.convert_worker,
            args=(list(self.files), output_dir),
            daemon=True
        )
        worker.start()

    def convert_worker(self, files, output_dir):
        successful = 0
        failed = 0
        skipped = 0
        total = len(files)

        try:
            for index, sas_file in enumerate(files, start=1):
                try:
                    if not sas_file.is_file():
                        failed += 1
                        self.events.put((
                            "log", f"FAILED: File not found: {sas_file}"
                        ))
                        continue

                    # Read SAS source
                    sas_code = sas_file.read_text(
                        encoding="utf-8-sig"
                    )

                    if not sas_code.strip():
                        failed += 1
                        self.events.put((
                            "log", f"FAILED: Empty file: {sas_file}"
                        ))
                        continue

                    self.events.put((
                        "log",
                        f"[{index}/{total}] Converting {sas_file.name}"
                    ))

                    # Call shared conversion engine
                    class_name, java_code = convert_sas_code(
                        sas_code,
                        sas_file.name
                    )

                    # Save Java file
                    java_file = output_dir / f"{class_name}.java"

                    # Do not overwrite existing files
                    with java_file.open(
                            "x", encoding="utf-8", newline="\n"
                    ) as output_file:
                        output_file.write(java_code + "\n")

                    successful += 1

                    self.events.put((
                        "log", f"SUCCESS: Saved {java_file}"
                    ))

                except subprocess.TimeoutExpired:
                    failed += 1
                    self.events.put((
                        "log", f"FAILED: Timeout: {sas_file.name}"
                    ))

                except Exception as error:
                    failed += 1
                    self.events.put((
                        "log", f"FAILED: {sas_file.name}: {error}"
                    ))

                self.events.put((
                    "progress", index * 100 / total
                ))

        finally:
            self.events.put((
                "finished", successful, failed, skipped, total
            ))

    def process_events(self):
        try:
            while True:
                event = self.events.get_nowait()

                if event[0] == "log":
                    self.add_log(event[1])
                elif event[0] == "progress":
                    self.progress.set(event[1])
                elif event[0] == "finished":
                    _, successful, failed, skipped, total = event
                    self.busy = False
                    self.convert_button.config(state="normal")
                    self.status.set(
                        f"Finished: {successful} converted, "
                        f"{failed} failed, {skipped} skipped"
                    )
                    self.add_log(
                        f"Completed. Total files: {total}"
                    )
                    messagebox.showinfo(
                        "Conversion finished",
                        f"Converted: {successful}\n"
                        f"Failed: {failed}\n"
                        f"Skipped: {skipped}"
                    )
        except queue.Empty:
            pass

        self.root.after(100, self.process_events)


if __name__ == "__main__":
    root = tk.Tk()
    app = SASJavaConverter(root)
    root.mainloop()