
import hashlib
import io

import cv2
import numpy as np
import streamlit as st
from PIL import Image, ImageDraw
from streamlit_drawable_canvas import st_canvas
from streamlit_image_coordinates import streamlit_image_coordinates


# =========================================================
# CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="Solder Sight",
    page_icon="🎯",
    layout="wide",
)

# All image panels use these fixed dimensions.
BOX_CANVAS_W = 900
BOX_CANVAS_H = 560

CROP_CANVAS_W = 900
CROP_CANVAS_H = 500

st.title("🎯 Solder Sight")
st.caption("Draw a work area · Calibrate dimensions · Select solder joints")

st.warning(
    "This application creates a coordinate table and G-code preview only. "
    "It does not control your soldering hardware."
)


# =========================================================
# SESSION STATE
# =========================================================

STATE_DEFAULTS = {
    "image_hash": None,
    "box_original": None,
    "width_mm": 100.0,
    "height_mm": 60.0,
    "calibrated": False,
    "targets": [],
    "last_target_click": None,
}

for key, value in STATE_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =========================================================
# IMAGE NORMALIZATION
# Fixed-size image, preserved aspect ratio, centered
# =========================================================

def fit_image(image, canvas_w, canvas_h, background=(35, 35, 35)):
    """
    Fit an image into a fixed-size panel without distorting it.

    Returns:
        canvas_image: fixed-size RGB PIL image
        scale: resize scale from source image to panel
        offset_x, offset_y: image position within panel
        displayed_w, displayed_h: fitted image dimensions
    """
    image = image.convert("RGB")
    src_w, src_h = image.size

    scale = min(canvas_w / src_w, canvas_h / src_h)

    displayed_w = max(1, round(src_w * scale))
    displayed_h = max(1, round(src_h * scale))

    resized = image.resize(
        (displayed_w, displayed_h),
        Image.Resampling.LANCZOS,
    )

    canvas_image = Image.new(
        "RGB",
        (canvas_w, canvas_h),
        background,
    )

    offset_x = (canvas_w - displayed_w) // 2
    offset_y = (canvas_h - displayed_h) // 2

    canvas_image.paste(resized, (offset_x, offset_y))

    return (
        canvas_image,
        scale,
        offset_x,
        offset_y,
        displayed_w,
        displayed_h,
    )


def panel_to_original(x, y, scale, offset_x, offset_y):
    """Convert panel coordinates to original image pixel coordinates."""
    return (
        (x - offset_x) / scale,
        (y - offset_y) / scale,
    )


def original_to_panel(x, y, scale, offset_x, offset_y):
    """Convert original image pixels to panel coordinates."""
    return (
        x * scale + offset_x,
        y * scale + offset_y,
    )


def make_annotated_crop(crop, targets, crop_box):
    """Draw target markers over the original-resolution crop."""
    result = crop.copy()
    draw = ImageDraw.Draw(result)

    for index, (x, y) in enumerate(targets, start=1):
        radius = max(5, min(14, round(min(result.size) * 0.012)))

        draw.ellipse(
            (
                x - radius,
                y - radius,
                x + radius,
                y + radius,
            ),
            outline="red",
            width=3,
        )

        draw.text(
            (x + radius + 3, y - radius),
            str(index),
            fill="red",
            stroke_width=1,
            stroke_fill="white",
        )

    return result


# =========================================================
# PERSPECTIVE TRANSFORM
# Origin = bottom-left of selected box
# =========================================================

def make_transform(box, width_mm, height_mm):
    x1, y1, x2, y2 = box

    source = np.array(
        [
            [x1, y1],  # top-left
            [x2, y1],  # top-right
            [x2, y2],  # bottom-right
            [x1, y2],  # bottom-left
        ],
        dtype=np.float32,
    )

    destination = np.array(
        [
            [0, height_mm],
            [width_mm, height_mm],
            [width_mm, 0],
            [0, 0],
        ],
        dtype=np.float32,
    )

    return cv2.getPerspectiveTransform(source, destination)


def pixel_to_mm(point, transform):
    point_array = np.array(
        [[point]],
        dtype=np.float32,
    )

    converted = cv2.perspectiveTransform(
        point_array,
        transform,
    )

    return (
        float(converted[0][0][0]),
        float(converted[0][0][1]),
    )


# =========================================================
# POPUP FOR BOX DIMENSIONS
# =========================================================

@st.dialog("Set work-area dimensions")
def dimensions_popup(box):
    st.write(
        "Enter the actual physical dimensions of the rectangular "
        "area you selected."
    )

    with st.form("dimensions_form"):
        width = st.number_input(
            "Box width (mm)",
            min_value=0.1,
            max_value=10000.0,
            value=float(st.session_state.width_mm),
            step=1.0,
        )

        height = st.number_input(
            "Box height (mm)",
            min_value=0.1,
            max_value=10000.0,
            value=float(st.session_state.height_mm),
            step=1.0,
        )

        submitted = st.form_submit_button(
            "Confirm dimensions",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        st.session_state.box_original = box
        st.session_state.width_mm = float(width)
        st.session_state.height_mm = float(height)
        st.session_state.calibrated = True
        st.session_state.targets = []
        st.session_state.last_target_click = None
        st.rerun()


# =========================================================
# UPLOAD IMAGE
# =========================================================

st.subheader("1. Upload PCB image")

uploaded = st.file_uploader(
    "Choose an image",
    type=["png", "jpg", "jpeg", "webp", "bmp"],
)

if uploaded is None:
    st.info("Upload a PCB image to start.")
    st.stop()

try:
    original_image = Image.open(
        io.BytesIO(uploaded.getvalue())
    ).convert("RGB")
except Exception:
    st.error("The uploaded file could not be opened as an image.")
    st.stop()

original_w, original_h = original_image.size

image_hash = hashlib.sha256(
    uploaded.getvalue()
).hexdigest()

if st.session_state.image_hash != image_hash:
    st.session_state.image_hash = image_hash
    st.session_state.box_original = None
    st.session_state.calibrated = False
    st.session_state.targets = []
    st.session_state.last_target_click = None

st.caption(
    f"Original resolution: {original_w} × {original_h} pixels"
)


# =========================================================
# DRAW THE BOX
# =========================================================

if not st.session_state.calibrated:

    st.subheader("2. Draw the work-area box")

    st.write(
        "Drag from one corner to the opposite corner around the PCB area "
        "you want to work on. The image panel has a fixed size; the image "
        "itself keeps its aspect ratio."
    )

    box_panel, box_scale, box_off_x, box_off_y, _, _ = fit_image(
        original_image,
        BOX_CANVAS_W,
        BOX_CANVAS_H,
    )

    canvas_result = st_canvas(
        fill_color="rgba(0, 180, 255, 0.15)",
        stroke_width=2,
        stroke_color="#00B4FF",
        background_image=box_panel,
        update_streamlit=True,
        height=BOX_CANVAS_H,
        width=BOX_CANVAS_W,
        drawing_mode="rect",
        display_toolbar=True,
        key=f"rectangle_canvas_{image_hash}",
    )

    if st.button("Reset box drawing"):
        st.session_state.box_original = None
        st.session_state.calibrated = False
        st.rerun()

    rectangle = None

    if (
        canvas_result.json_data is not None
        and canvas_result.json_data.get("objects")
    ):
        objects = canvas_result.json_data["objects"]

        rectangles = [
            obj for obj in objects
            if obj.get("type") == "rect"
        ]

        if rectangles:
            # Use the most recently drawn rectangle.
            obj = rectangles[-1]

            left = float(obj.get("left", 0))
            top = float(obj.get("top", 0))
            rect_w = float(obj.get("width", 0)) * float(
                obj.get("scaleX", 1)
            )
            rect_h = float(obj.get("height", 0)) * float(
                obj.get("scaleY", 1)
            )

            # Rectangle coordinates in the panel.
            px1 = min(left, left + rect_w)
            py1 = min(top, top + rect_h)
            px2 = max(left, left + rect_w)
            py2 = max(top, top + rect_h)

            # Map panel coordinates back to the original image.
            ox1, oy1 = panel_to_original(
                px1, py1, box_scale, box_off_x, box_off_y
            )
            ox2, oy2 = panel_to_original(
                px2, py2, box_scale, box_off_x, box_off_y
            )

            # Clip box to image boundaries.
            ox1 = max(0.0, min(float(original_w - 1), ox1))
            ox2 = max(0.0, min(float(original_w - 1), ox2))
            oy1 = max(0.0, min(float(original_h - 1), oy1))
            oy2 = max(0.0, min(float(original_h - 1), oy2))

            if ox2 - ox1 >= 5 and oy2 - oy1 >= 5:
                rectangle = (ox1, oy1, ox2, oy2)

    if rectangle is not None:
        st.success("Rectangle detected.")

        x1, y1, x2, y2 = rectangle
        preview = original_image.copy()
        draw = ImageDraw.Draw(preview)
        draw.rectangle((x1, y1, x2, y2), outline="cyan", width=5)

        preview_panel, _, _, _, _, _ = fit_image(
            preview,
            BOX_CANVAS_W,
            BOX_CANVAS_H,
        )

        st.image(
            preview_panel,
            caption="Preview of the selected box",
            use_container_width=False,
        )

        if st.button(
            "Set box width and height",
            type="primary",
            use_container_width=True,
        ):
            dimensions_popup(rectangle)

    st.stop()


# =========================================================
# CALIBRATED CROP
# =========================================================

box = st.session_state.box_original
x1, y1, x2, y2 = box

# Crop the selected region from the original-resolution image.
crop = original_image.crop(
    (
        int(round(x1)),
        int(round(y1)),
        int(round(x2)),
        int(round(y2)),
    )
)

if crop.width < 2 or crop.height < 2:
    st.error("The selected box is too small. Reset and draw it again.")
    st.session_state.calibrated = False
    st.stop()

st.subheader("3. Selected work area")

dim_col1, dim_col2, dim_col3 = st.columns(3)

dim_col1.metric("Box width", f"{st.session_state.width_mm:.2f} mm")
dim_col2.metric("Box height", f"{st.session_state.height_mm:.2f} mm")
dim_col3.metric("Crop resolution", f"{crop.width} × {crop.height} px")

if st.button("Redraw box / change dimensions"):
    st.session_state.calibrated = False
    st.session_state.box_original = None
    st.session_state.targets = []
    st.session_state.last_target_click = None
    st.rerun()


# =========================================================
# TARGET POINT SELECTION
# =========================================================

st.subheader("4. Select candidate solder joints")

st.write(
    "Click a solder joint in the crop, then press **Add target point**. "
    "Coordinates are measured from the bottom-left of the selected box."
)

crop_panel, crop_scale, crop_off_x, crop_off_y, _, _ = fit_image(
    crop,
    CROP_CANVAS_W,
    CROP_CANVAS_H,
)

annotated_crop = make_annotated_crop(
    crop,
    st.session_state.targets,
    box,
)

crop_panel, crop_scale, crop_off_x, crop_off_y, _, _ = fit_image(
    annotated_crop,
    CROP_CANVAS_W,
    CROP_CANVAS_H,
)

selected_crop_pixel = None

click_result = streamlit_image_coordinates(
    crop_panel,
    key=f"target_picker_{image_hash}_{len(st.session_state.targets)}",
)

if click_result is not None:
    click_x = float(click_result["x"])
    click_y = float(click_result["y"])

    # Convert panel coordinates into crop-image pixels.
    crop_x, crop_y = panel_to_original(
        click_x,
        click_y,
        crop_scale,
        crop_off_x,
        crop_off_y,
    )

    if (
        0 <= crop_x < crop.width
        and 0 <= crop_y < crop.height
    ):
        selected_crop_pixel = (crop_x, crop_y)

if selected_crop_pixel is not None:
    st.write(
        "Selected crop pixel: "
        f"X = {selected_crop_pixel[0]:.1f}, "
        f"Y = {selected_crop_pixel[1]:.1f}"
    )

    if st.button(
        "Add target point",
        type="primary",
        key=f"add_target_{len(st.session_state.targets)}",
    ):
        # Store the point in original-image pixel coordinates.
        original_point = (
            x1 + selected_crop_pixel[0],
            y1 + selected_crop_pixel[1],
        )

        st.session_state.targets.append(original_point)
        st.session_state.last_target_click = None
        st.rerun()

if st.session_state.targets:
    if st.button("Clear all target points"):
        st.session_state.targets = []
        st.session_state.last_target_click = None
        st.rerun()


# =========================================================
# COORDINATE CONVERSION
# =========================================================

transform = make_transform(
    box,
    st.session_state.width_mm,
    st.session_state.height_mm,
)

converted_points = []

for index, point in enumerate(
    st.session_state.targets,
    start=1,
):
    x_mm, y_mm = pixel_to_mm(point, transform)

    converted_points.append(
        {
            "Point": index,
            "Image X (px)": round(point[0], 2),
            "Image Y (px)": round(point[1], 2),
            "X (mm)": round(x_mm, 3),
            "Y (mm)": round(y_mm, 3),
        }
    )


# =========================================================
# RESULTS
# =========================================================

st.subheader("5. Coordinate results")

if converted_points:
    st.dataframe(
        converted_points,
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No target points selected yet.")


# =========================================================
# G-CODE
# =========================================================

st.subheader("6. G-code preview")

st.caption(
    "Only XY positioning is generated. No Z motion or soldering action "
    "is included. These coordinates are relative to the selected box, "
    "not automatically aligned to your machine's home position."
)

if converted_points:
    gcode_lines = [
        "; Solder Sight - generated XY points",
        "; Review and validate before machine execution",
        "G21 ; Units: millimetres",
        "G90 ; Absolute positioning",
    ]

    for point in converted_points:
        gcode_lines.append(
            f"G0 X{point['X (mm)']:.3f} Y{point['Y (mm)']:.3f}"
        )

    gcode_lines.append("M2 ; End program")
    gcode = "\n".join(gcode_lines)

    st.code(gcode, language="text")

    st.download_button(
        "Download G-code",
        data=gcode,
        file_name="solder_sight_points.gcode",
        mime="text/plain",
    )

    csv_data = "Point,Image X (px),Image Y (px),X (mm),Y (mm)\n"
    for point in converted_points:
        csv_data += (
            f"{point['Point']},"
            f"{point['Image X (px)']},"
            f"{point['Image Y (px)']},"
            f"{point['X (mm)']},"
            f"{point['Y (mm)']}\n"
        )

    st.download_button(
        "Download coordinates CSV",
        data=csv_data,
        file_name="solder_sight_coordinates.csv",
        mime="text/csv",
    )

st.divider()
st.caption(
    "Calibration accuracy depends on correct corner selection and "
    "correct physical dimensions. This rectangular calibration is an "
    "approximation if the real work area is not rectangular in the image. "
    "Verify machine offsets, axis directions, limits, and safe movement "
    "before using any coordinates."
)
