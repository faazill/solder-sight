
import hashlib
import io

import cv2
import numpy as np
import streamlit as st
from PIL import Image
from streamlit_image_coordinates import streamlit_image_coordinates


# --------------------------------------------------
# Page configuration
# --------------------------------------------------

st.set_page_config(
    page_title="Solder Sight",
    page_icon="🎯",
    layout="wide",
)

st.title("🎯 Solder Sight")
st.write(
    "Select a PCB work area, calibrate its physical dimensions, "
    "identify soldering points, and generate G-code coordinates."
)

st.warning(
    "This app generates a G-code preview only. Verify your machine's "
    "origin, offsets, axis directions, travel limits, and safe Z height "
    "before running any generated code."
)


# --------------------------------------------------
# Session state
# --------------------------------------------------

DEFAULTS = {
    "image_hash": None,
    "corners": [],
    "targets": [],
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# --------------------------------------------------
# Image utilities
# --------------------------------------------------

def make_display_image(image, max_dimension=1000):
    """
    Resize an image for browser interaction.

    Returns:
        display_image: resized PIL image
        scale: display width / original width
    """
    original_width, original_height = image.size

    scale = min(
        1.0,
        max_dimension / max(original_width, original_height),
    )

    display_width = max(1, round(original_width * scale))
    display_height = max(1, round(original_height * scale))

    display_image = image.resize(
        (display_width, display_height),
        Image.Resampling.LANCZOS,
    )

    return display_image, scale


def annotate_image(image, scale, corners, targets):
    """Draw the selected corners and target points."""
    display_image, _ = make_display_image(image)
    array = cv2.cvtColor(
        np.array(display_image),
        cv2.COLOR_RGB2BGR,
    )

    corner_labels = ["TL", "TR", "BR", "BL"]

    for index, point in enumerate(corners):
        x = round(point[0] * scale)
        y = round(point[1] * scale)

        cv2.circle(array, (x, y), 7, (0, 255, 0), -1)
        cv2.putText(
            array,
            corner_labels[index],
            (x + 8, y - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 180, 0),
            2,
        )

    for index, point in enumerate(targets):
        x = round(point[0] * scale)
        y = round(point[1] * scale)

        cv2.drawMarker(
            array,
            (x, y),
            (0, 0, 255),
            cv2.MARKER_CROSS,
            18,
            2,
        )
        cv2.putText(
            array,
            str(index + 1),
            (x + 8, y - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2,
        )

    return Image.fromarray(
        cv2.cvtColor(array, cv2.COLOR_BGR2RGB)
    )


# --------------------------------------------------
# Perspective calibration
# --------------------------------------------------

def create_perspective_transform(corners, width_mm, height_mm):
    """
    Convert camera-image coordinates to physical XY coordinates.

    Corner order:
        0 = top-left
        1 = top-right
        2 = bottom-right
        3 = bottom-left

    Physical origin:
        bottom-left = (0, 0)
        bottom-right = (width_mm, 0)
        top-right = (width_mm, height_mm)
        top-left = (0, height_mm)
    """
    source = np.array(corners, dtype=np.float32)

    destination = np.array(
        [
            [0.0, height_mm],
            [width_mm, height_mm],
            [width_mm, 0.0],
            [0.0, 0.0],
        ],
        dtype=np.float32,
    )

    return cv2.getPerspectiveTransform(source, destination)


def pixel_to_mm(point, transform):
    """Convert one original-image pixel coordinate to physical XY."""
    source_point = np.array(
        [[point]],
        dtype=np.float32,
    )

    result = cv2.perspectiveTransform(
        source_point,
        transform,
    )

    x_mm, y_mm = result[0][0]
    return float(x_mm), float(y_mm)


# --------------------------------------------------
# Upload image
# --------------------------------------------------

uploaded_file = st.file_uploader(
    "Upload a PCB or work-area image",
    type=["png", "jpg", "jpeg", "bmp", "webp"],
)

if uploaded_file is None:
    st.info(
        "Upload an image to begin. For accurate calibration, "
        "the selected four corners should define a flat, rectangular "
        "work area."
    )
    st.stop()

image_bytes = uploaded_file.getvalue()
current_hash = hashlib.sha256(image_bytes).hexdigest()

# Clear old selections if the uploaded image changes.
if st.session_state.image_hash != current_hash:
    st.session_state.image_hash = current_hash
    st.session_state.corners = []
    st.session_state.targets = []

image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
original_width, original_height = image.size
display_image, scale = make_display_image(image)

st.caption(
    f"Image size: {original_width} × {original_height} pixels"
)


# --------------------------------------------------
# Physical dimensions
# --------------------------------------------------

st.subheader("1. Set work-area dimensions")

dimension_col1, dimension_col2 = st.columns(2)

with dimension_col1:
    width_mm = st.number_input(
        "Work-area width (mm)",
        min_value=0.1,
        value=100.0,
        step=1.0,
    )

with dimension_col2:
    height_mm = st.number_input(
        "Work-area height (mm)",
        min_value=0.1,
        value=60.0,
        step=1.0,
    )

st.caption(
    "Enter the real physical width and height between the four "
    "corners you will select—not the PCB's approximate overall size."
)


# --------------------------------------------------
# Select the four corners
# --------------------------------------------------

st.subheader("2. Calibrate the work area")

corner_names = [
    "Top-left",
    "Top-right",
    "Bottom-right",
    "Bottom-left",
]

corner_count = len(st.session_state.corners)

if corner_count < 4:
    st.write(
        f"Click the **{corner_names[corner_count]}** corner in the image, "
        "then press **Add corner**. Select the corners in the displayed order."
    )

    click = streamlit_image_coordinates(
        display_image,
        key=f"calibration_clicker_{corner_count}",
    )

    if click is not None:
        clicked_x = float(click["x"])
        clicked_y = float(click["y"])

        st.caption(
            f"Selected image point: "
            f"({clicked_x:.1f}, {clicked_y:.1f})"
        )

        if st.button(
            f"Add {corner_names[corner_count]} corner",
            key=f"add_corner_{corner_count}",
        ):
            # Convert displayed-image coordinates to original-image pixels.
            original_point = (
                clicked_x / scale,
                clicked_y / scale,
            )

            st.session_state.corners.append(original_point)
            st.rerun()

else:
    st.success("All four corners have been selected.")

    if st.button("Reset corners"):
        st.session_state.corners = []
        st.session_state.targets = []
        st.rerun()

# Show selected calibration points.
if st.session_state.corners:
    st.image(
        annotate_image(
            image,
            scale,
            st.session_state.corners,
            [],
        ),
        caption="Selected work-area corners",
        use_container_width=True,
    )

if len(st.session_state.corners) != 4:
    st.info("Select all four corners to enable coordinate conversion.")
    st.stop()


# --------------------------------------------------
# Build coordinate transform
# --------------------------------------------------

transform = create_perspective_transform(
    st.session_state.corners,
    width_mm,
    height_mm,
)

st.subheader("3. Select soldering points")

st.write(
    "Click the desired solder joint in the image, then press "
    "**Add target point**. Repeat for each point."
)

annotated_image = annotate_image(
    image,
    scale,
    st.session_state.corners,
    st.session_state.targets,
)

target_click = streamlit_image_coordinates(
    annotated_image,
    key=f"target_clicker_{len(st.session_state.targets)}",
)

if target_click is not None:
    selected_display_x = float(target_click["x"])
    selected_display_y = float(target_click["y"])

    selected_pixel = (
        selected_display_x / scale,
        selected_display_y / scale,
    )

    selected_x_mm, selected_y_mm = pixel_to_mm(
        selected_pixel,
        transform,
    )

    st.write(
        f"Selected physical coordinate: "
        f"**X = {selected_x_mm:.3f} mm, "
        f"Y = {selected_y_mm:.3f} mm**"
    )

    if st.button(
        "Add target point",
        key=f"add_target_{len(st.session_state.targets)}",
    ):
        st.session_state.targets.append(selected_pixel)
        st.rerun()

if st.session_state.targets:
    if st.button("Clear all target points"):
        st.session_state.targets = []
        st.rerun()


# --------------------------------------------------
# Coordinate table
# --------------------------------------------------

st.subheader("4. Converted coordinates")

converted_points = []

for index, point in enumerate(st.session_state.targets, start=1):
    x_mm, y_mm = pixel_to_mm(point, transform)

    converted_points.append(
        {
            "Point": index,
            "Image X (px)": round(point[0], 2),
            "Image Y (px)": round(point[1], 2),
            "Machine-plan X (mm)": round(x_mm, 3),
            "Machine-plan Y (mm)": round(y_mm, 3),
        }
    )

if converted_points:
    st.dataframe(
        converted_points,
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No target points have been added yet.")


# --------------------------------------------------
# G-code preview and download
# --------------------------------------------------

st.subheader("5. G-code preview")

st.caption(
    "The generated file contains XY positioning moves only. "
    "It does not include Z-axis motion, soldering commands, "
    "tool activation, or machine-specific homing."
)

if converted_points:
    gcode_lines = [
        "; Generated by Solder Sight",
        "; Verify machine coordinates and offsets before use",
        "G21 ; Units in millimetres",
        "G90 ; Absolute positioning",
    ]

    for point in converted_points:
        gcode_lines.append(
            f"G0 X{point['Machine-plan X (mm)']:.3f} "
            f"Y{point['Machine-plan Y (mm)']:.3f}"
        )

    gcode_lines.append("M2 ; End program")

    gcode = "\n".join(gcode_lines)

    st.code(gcode, language="gcode")

    st.download_button(
        label="Download G-code",
        data=gcode,
        file_name="solder_sight_points.gcode",
        mime="text/plain",
    )

else:
    st.write("Add at least one target point to generate G-code.")

st.divider()

st.caption(
    "Calibration assumes a flat work surface. The selected corners must "
    "be accurate, and the physical dimensions must be measured correctly. "
    "These coordinates are relative to the selected rectangle's bottom-left "
    "corner; they are not automatically calibrated to your machine's home "
    "position or tool offset."
)
