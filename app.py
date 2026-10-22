
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import cv2
import numpy as np
from PIL import Image, ImageTk


class CameraGCodeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Camera to G-code Coordinate Mapper")
        self.root.geometry("1200x800")

        self.cap = None
        self.frame = None
        self.photo = None

        # Four image points: TL, TR, BR, BL
        self.corners = []
        self.targets = []
        self.H = None

        self.mode = "calibrate"
        self.display_scale = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.display_w = 1
        self.display_h = 1

        self.width_var = tk.StringVar(value="100")
        self.height_var = tk.StringVar(value="60")
        self.camera_var = tk.StringVar(value="0")
        self.status_var = tk.StringVar(
            value="Open camera, then click the four work-area corners."
        )

        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.update_camera()

    def build_ui(self):
        panel = ttk.Frame(self.root, padding=8)
        panel.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Label(
            panel, text="CAMERA / G-CODE",
            font=("Arial", 15, "bold")
        ).pack(anchor="w", pady=8)

        ttk.Label(panel, text="Camera index").pack(anchor="w")
        ttk.Entry(
            panel, textvariable=self.camera_var, width=12
        ).pack(anchor="w", pady=3)

        ttk.Button(
            panel, text="Open camera", command=self.open_camera
        ).pack(fill=tk.X, pady=4)

        ttk.Separator(panel).pack(fill=tk.X, pady=10)

        ttk.Label(panel, text="Work-area width (mm)").pack(anchor="w")
        ttk.Entry(
            panel, textvariable=self.width_var
        ).pack(fill=tk.X, pady=3)

        ttk.Label(panel, text="Work-area height (mm)").pack(anchor="w")
        ttk.Entry(
            panel, textvariable=self.height_var
        ).pack(fill=tk.X, pady=3)

        ttk.Button(
            panel, text="Start corner calibration",
            command=self.start_calibration
        ).pack(fill=tk.X, pady=5)

        ttk.Button(
            panel, text="Select target points",
            command=self.start_targets
        ).pack(fill=tk.X, pady=5)

        ttk.Button(
            panel, text="Undo last point",
            command=self.undo
        ).pack(fill=tk.X, pady=3)

        ttk.Button(
            panel, text="Reset all",
            command=self.reset
        ).pack(fill=tk.X, pady=3)

        ttk.Separator(panel).pack(fill=tk.X, pady=10)

        ttk.Label(panel, text="Selected coordinates").pack(anchor="w")

        self.coords = tk.Listbox(panel, width=35, height=12)
        self.coords.pack(fill=tk.BOTH, expand=True, pady=5)

        ttk.Button(
            panel, text="Generate G-code preview",
            command=self.show_gcode
        ).pack(fill=tk.X, pady=3)

        ttk.Label(
            panel, textvariable=self.status_var,
            wraplength=250
        ).pack(anchor="w", pady=10)

        # Camera canvas
        view = ttk.Frame(self.root, padding=8)
        view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(
            view, background="#202020",
            cursor="crosshair", highlightthickness=0
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Configure>", lambda _e: self.render())

    def open_camera(self):
        try:
            index = int(self.camera_var.get())
        except ValueError:
            messagebox.showerror("Camera", "Camera index must be an integer.")
            return

        if self.cap is not None:
            self.cap.release()

        self.cap = cv2.VideoCapture(index)

        if not self.cap.isOpened():
            self.cap.release()
            self.cap = None
            messagebox.showerror(
                "Camera", f"Could not open camera {index}."
            )
            return

        self.status_var.set("Camera opened. Calibrate the four corners.")

    def update_camera(self):
        if self.cap is not None:
            ok, frame = self.cap.read()
            if ok:
                self.frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self.render()

        self.root.after(30, self.update_camera)

    def render(self):
        self.canvas.delete("all")

        if self.frame is None:
            self.canvas.create_text(
                max(100, self.canvas.winfo_width() // 2),
                max(100, self.canvas.winfo_height() // 2),
                text="Open the camera to begin",
                fill="white", font=("Arial", 16)
            )
            return

        fh, fw = self.frame.shape[:2]
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())

        scale = min(cw / fw, ch / fh)
        self.display_scale = scale
        self.display_w = int(fw * scale)
        self.display_h = int(fh * scale)
        self.offset_x = (cw - self.display_w) // 2
        self.offset_y = (ch - self.display_h) // 2

        resized = cv2.resize(
            self.frame, (self.display_w, self.display_h)
        )
        self.photo = ImageTk.PhotoImage(Image.fromarray(resized))

        self.canvas.create_image(
            self.offset_x, self.offset_y,
            anchor=tk.NW, image=self.photo
        )

        # Draw calibrated quadrilateral
        if self.corners:
            pts = [self.image_to_canvas(p) for p in self.corners]

            for i, (x, y) in enumerate(pts):
                self.canvas.create_oval(
                    x - 5, y - 5, x + 5, y + 5,
                    fill="yellow", outline="black"
                )
                self.canvas.create_text(
                    x + 10, y - 10, text=str(i + 1),
                    fill="yellow", anchor=tk.W
                )

            if len(pts) >= 2:
                for i in range(len(pts) - 1):
                    self.canvas.create_line(
                        *pts[i], *pts[i + 1],
                        fill="yellow", width=2
                    )

            if len(pts) == 4:
                self.canvas.create_line(
                    *pts[3], *pts[0],
                    fill="yellow", width=2
                )

        # Draw target points
        for i, p in enumerate(self.targets):
            x, y = self.image_to_canvas(p["pixel"])
            self.canvas.create_oval(
                x - 5, y - 5, x + 5, y + 5,
                fill="red", outline="white"
            )
            self.canvas.create_text(
                x + 8, y + 8, text=str(i + 1),
                fill="white", anchor=tk.NW
            )

    def canvas_to_image(self, x, y):
        # Convert displayed coordinates back to original camera pixels
        ix = (x - self.offset_x) / self.display_scale
        iy = (y - self.offset_y) / self.display_scale

        fh, fw = self.frame.shape[:2]
        if not (0 <= ix < fw and 0 <= iy < fh):
            return None

        return [float(ix), float(iy)]

    def image_to_canvas(self, p):
        return (
            self.offset_x + p[0] * self.display_scale,
            self.offset_y + p[1] * self.display_scale
        )

    def on_click(self, event):
        if self.frame is None:
            return

        p = self.canvas_to_image(event.x, event.y)
        if p is None:
            return

        if self.mode == "calibrate":
            if len(self.corners) >= 4:
                self.status_var.set(
                    "Four corners selected. Start calibration again "
                    "to replace them."
                )
                return

            self.corners.append(p)

            if len(self.corners) == 4:
                self.calculate_homography()

        elif self.mode == "targets":
            if self.H is None:
                messagebox.showwarning(
                    "Calibration", "Calibrate the work area first."
                )
                return

            xy = cv2.perspectiveTransform(
                np.array([[p]], dtype=np.float32), self.H
            )[0][0]

            try:
                w = float(self.width_var.get())
                h = float(self.height_var.get())
            except ValueError:
                messagebox.showerror(
                    "Dimensions", "Enter valid width and height."
                )
                return

            if not (0 <= xy[0] <= w and 0 <= xy[1] <= h):
                self.status_var.set(
                    "Target is outside the calibrated work area."
                )
                return

            self.targets.append({
                "pixel": p,
                "x": float(xy[0]),
                "y": float(xy[1])
            })

            self.coords.insert(
                tk.END,
                f"P{len(self.targets)}: X{xy[0]:.3f} Y{xy[1]:.3f} mm"
            )
            self.status_var.set(
                f"Point added: X={xy[0]:.3f}, Y={xy[1]:.3f} mm"
            )

        self.render()

    def calculate_homography(self):
        try:
            w = float(self.width_var.get())
            h = float(self.height_var.get())
        except ValueError:
            messagebox.showerror(
                "Dimensions", "Enter numeric width and height."
            )
            self.corners = []
            return

        if w <= 0 or h <= 0:
            messagebox.showerror(
                "Dimensions", "Width and height must be positive."
            )
            self.corners = []
            return

        src = np.array(self.corners, dtype=np.float32)

        # Physical coordinate system:
        # origin = bottom-left; X rightward, Y upward.
        dst = np.array([
            [0, h],  # image top-left
            [w, h],  # image top-right
            [w, 0],  # image bottom-right
            [0, 0]   # image bottom-left
        ], dtype=np.float32)

        if abs(cv2.contourArea(src)) < 100:
            messagebox.showerror(
                "Calibration",
                "The selected corners are too close together."
            )
            self.corners = []
            return

        self.H = cv2.getPerspectiveTransform(src, dst)
        self.mode = "targets"
        self.status_var.set(
            "Calibrated. Click inside the work area to add targets."
        )

    def start_calibration(self):
        self.corners = []
        self.targets = []
        self.H = None
        self.coords.delete(0, tk.END)
        self.mode = "calibrate"
        self.status_var.set(
            "Click four corners in order: top-left, top-right, "
            "bottom-right, bottom-left."
        )
        self.render()

    def start_targets(self):
        if self.H is None:
            messagebox.showwarning(
                "Calibration", "Select the four corners first."
            )
            return
        self.mode = "targets"
        self.status_var.set("Click the image to add target points.")

    def undo(self):
        if self.mode == "calibrate" and self.corners:
            self.corners.pop()
        elif self.targets:
            self.targets.pop()
            self.coords.delete(tk.END)
        self.render()

    def reset(self):
        self.corners = []
        self.targets = []
        self.H = None
        self.coords.delete(0, tk.END)
        self.mode = "calibrate"
        self.status_var.set("Reset. Select four corners to calibrate.")
        self.render()

    def show_gcode(self):
        if not self.targets:
            messagebox.showinfo("G-code", "Select at least one target.")
            return

        lines = ["G21  ; Units in millimeters", "G90  ; Absolute coordinates"]

        for p in self.targets:
            lines.append(f"G0 X{p['x']:.3f} Y{p['y']:.3f}")

        lines.append("; Preview only - not sent to hardware")
        code = "\n".join(lines)

        win = tk.Toplevel(self.root)
        win.title("G-code Preview")
        win.geometry("560x400")

        text = tk.Text(win, wrap=tk.NONE, font=("Courier New", 11))
        text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        text.insert("1.0", code)

        buttons = ttk.Frame(win, padding=8)
        buttons.pack(fill=tk.X)

        def copy_code():
            self.root.clipboard_clear()
            self.root.clipboard_append(code)
            self.status_var.set("G-code preview copied to clipboard.")

        def save_code():
            path = filedialog.asksaveasfilename(
                defaultextension=".gcode",
                filetypes=[("G-code files", "*.gcode"), ("Text files", "*.txt")]
            )
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(code)
                messagebox.showinfo("Saved", f"Saved to {path}")

        ttk.Button(
            buttons, text="Copy", command=copy_code
        ).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            buttons, text="Save", command=save_code
        ).pack(side=tk.LEFT, padx=4)

    def close(self):
        if self.cap is not None:
            self.cap.release()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = CameraGCodeApp(root)
    root.mainloop()
