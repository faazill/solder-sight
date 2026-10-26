from geometry import crop_window, merge_points, mm_to_px, order_points, px_to_mm

BOX = (100, 50, 300, 150)  # 200 x 100 px
W, H = 80.0, 40.0


def test_bottom_left_is_origin():
    assert px_to_mm((100, 150), BOX, W, H) == (0.0, 0.0)


def test_top_right_is_full_size():
    assert px_to_mm((300, 50), BOX, W, H) == (80.0, 40.0)


def test_roundtrip():
    x, y = px_to_mm((187.5, 92.0), BOX, W, H)
    px, py = mm_to_px((x, y), BOX, W, H)
    assert abs(px - 187.5) < 1e-9 and abs(py - 92.0) < 1e-9


def test_crop_window_clamps_to_image():
    assert crop_window(2, 2, 40, 200, 100) == (0, 0, 40, 40)
    assert crop_window(199, 99, 40, 200, 100) == (160, 60, 200, 100)


def test_merge_skips_near_duplicates():
    merged, added = merge_points([(10, 10)], [(12, 11), (50, 50)], min_dist=8)
    assert added == 1 and len(merged) == 2


def test_order_starts_near_start():
    pts = [(100, 0), (10, 0), (50, 0)]
    assert order_points(pts, (0, 0)) == [(10, 0), (50, 0), (100, 0)]
