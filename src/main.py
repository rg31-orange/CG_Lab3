import taichi as ti
import numpy as np

# ============================================================
# 初始化 Taichi
# ============================================================

# 如果 cuda 出问题，可以改成 ti.cpu
ti.init(arch=ti.gpu)

WIDTH = 800
HEIGHT = 800

MAX_CONTROL_POINTS = 100
NUM_SEGMENTS = 1000
BSPLINE_SEGMENTS_PER_SPAN = 100

MAX_CURVE_POINTS = (MAX_CONTROL_POINTS - 3) * BSPLINE_SEGMENTS_PER_SPAN + 1

pixels = ti.Vector.field(3, dtype=ti.f32, shape=(WIDTH, HEIGHT))
curve_points_field = ti.Vector.field(2, dtype=ti.f32, shape=MAX_CURVE_POINTS)


def de_casteljau(points, t):
    """
    De Casteljau 算法，计算贝塞尔曲线在 t 处的点。
    """
    temp = [np.array(p, dtype=np.float32) for p in points]

    while len(temp) > 1:
        next_points = []
        for i in range(len(temp) - 1):
            p = (1.0 - t) * temp[i] + t * temp[i + 1]
            next_points.append(p)
        temp = next_points

    return temp[0]


def generate_bezier_curve_points(control_points):
    """
    生成贝塞尔曲线采样点。
    """
    curve_np = np.full((MAX_CURVE_POINTS, 2), -10.0, dtype=np.float32)

    for i in range(NUM_SEGMENTS + 1):
        t = i / NUM_SEGMENTS
        curve_np[i] = de_casteljau(control_points, t)

    return curve_np, NUM_SEGMENTS + 1


def cubic_uniform_bspline_point(p0, p1, p2, p3, u):
    """
    均匀三次 B 样条曲线单段计算。
    """
    u2 = u * u
    u3 = u2 * u

    b0 = (-u3 + 3.0 * u2 - 3.0 * u + 1.0) / 6.0
    b1 = (3.0 * u3 - 6.0 * u2 + 4.0) / 6.0
    b2 = (-3.0 * u3 + 3.0 * u2 + 3.0 * u + 1.0) / 6.0
    b3 = u3 / 6.0

    p0 = np.array(p0, dtype=np.float32)
    p1 = np.array(p1, dtype=np.float32)
    p2 = np.array(p2, dtype=np.float32)
    p3 = np.array(p3, dtype=np.float32)

    return b0 * p0 + b1 * p1 + b2 * p2 + b3 * p3


def generate_bspline_curve_points(control_points):
    """
    生成均匀三次 B 样条曲线。
    """
    curve_np = np.full((MAX_CURVE_POINTS, 2), -10.0, dtype=np.float32)

    n = len(control_points)

    if n < 4:
        return curve_np, 0

    index = 0

    for span in range(n - 3):
        p0 = control_points[span]
        p1 = control_points[span + 1]
        p2 = control_points[span + 2]
        p3 = control_points[span + 3]

        for j in range(BSPLINE_SEGMENTS_PER_SPAN):
            u = j / BSPLINE_SEGMENTS_PER_SPAN
            curve_np[index] = cubic_uniform_bspline_point(p0, p1, p2, p3, u)
            index += 1

    curve_np[index] = cubic_uniform_bspline_point(
        control_points[n - 4],
        control_points[n - 3],
        control_points[n - 2],
        control_points[n - 1],
        1.0
    )
    index += 1

    return curve_np, index


@ti.kernel
def clear_pixels():
    """
    清空像素缓冲区。
    """
    for i, j in pixels:
        pixels[i, j] = ti.Vector([0.0, 0.0, 0.0])


@ti.func
def blend_pixel_safe(x: ti.i32, y: ti.i32, color: ti.types.vector(3, ti.f32), alpha: ti.f32):
    """
    带 alpha 的安全混合绘制。
    """
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        old_color = pixels[x, y]
        pixels[x, y] = old_color * (1.0 - alpha) + color * alpha


@ti.kernel
def draw_curve_kernel(n: ti.i32):
    """
    普通曲线绘制。
    """
    for i in range(n):
        pt = curve_points_field[i]

        x_pixel = ti.cast(pt[0] * WIDTH, ti.i32)
        y_pixel = ti.cast(pt[1] * HEIGHT, ti.i32)

        if 0 <= x_pixel < WIDTH and 0 <= y_pixel < HEIGHT:
            pixels[x_pixel, y_pixel] = ti.Vector([0.0, 1.0, 0.0])


@ti.kernel
def draw_curve_antialias_kernel(n: ti.i32):
    """
    反走样曲线绘制。
    """
    for i in range(n):
        pt = curve_points_field[i]

        fx = pt[0] * WIDTH
        fy = pt[1] * HEIGHT

        base_x = ti.cast(fx, ti.i32)
        base_y = ti.cast(fy, ti.i32)

        curve_color = ti.Vector([0.0, 1.0, 0.0])

        for dx in ti.static(range(-1, 2)):
            for dy in ti.static(range(-1, 2)):
                x = base_x + dx
                y = base_y + dy

                cx = ti.cast(x, ti.f32) + 0.5
                cy = ti.cast(y, ti.f32) + 0.5

                dist = ti.sqrt((fx - cx) * (fx - cx) + (fy - cy) * (fy - cy))
                alpha = ti.max(0.0, 1.0 - dist / 1.5)
                alpha = ti.min(alpha, 1.0)

                blend_pixel_safe(x, y, curve_color, alpha)


def print_help():
    print("============================================================")
    print("计算机图形学实验三：Bezier / B-Spline")
    print("------------------------------------------------------------")
    print("鼠标左键：添加控制点")
    print("C 键：清空")
    print("B 键：切换 Bezier / B-Spline")
    print("A 键：开启/关闭反走样")
    print("ESC：退出")
    print("============================================================")


def main():
    gui = ti.GUI("Experiment 3 - Bezier / B-Spline", res=(WIDTH, HEIGHT))

    control_points = []

    bspline_mode = False
    antialias = True

    print_help()

    while gui.running:
        # ----------------------------------------------------
        # 事件处理
        # ----------------------------------------------------
        for e in gui.get_events():
            if e.key == ti.GUI.ESCAPE:
                gui.running = False

            elif e.key == ti.GUI.LMB:
                if e.type == ti.GUI.PRESS:
                    if len(control_points) < MAX_CONTROL_POINTS:
                        pos = gui.get_cursor_pos()
                        control_points.append(pos)
                        print(f"添加控制点：{pos}，当前数量：{len(control_points)}")

            elif e.key == 'c':
                if e.type == ti.GUI.PRESS:
                    control_points = []
                    print("已清空控制点。")

            elif e.key == 'b':
                if e.type == ti.GUI.PRESS:
                    bspline_mode = not bspline_mode
                    if bspline_mode:
                        print("当前模式：B-Spline")
                    else:
                        print("当前模式：Bezier")

            elif e.key == 'a':
                if e.type == ti.GUI.PRESS:
                    antialias = not antialias
                    if antialias:
                        print("反走样：开启")
                    else:
                        print("反走样：关闭")

        clear_pixels()

        current_count = len(control_points)
        valid_curve_count = 0

        if not bspline_mode:
            if current_count >= 2:
                curve_np, valid_curve_count = generate_bezier_curve_points(control_points)
                curve_points_field.from_numpy(curve_np)
        else:
            if current_count >= 4:
                curve_np, valid_curve_count = generate_bspline_curve_points(control_points)
                curve_points_field.from_numpy(curve_np)

        if valid_curve_count > 0:
            if antialias:
                draw_curve_antialias_kernel(valid_curve_count)
            else:
                draw_curve_kernel(valid_curve_count)

        # ----------------------------------------------------
        # 先显示 pixels
        # ----------------------------------------------------
        gui.set_image(pixels)

        # ----------------------------------------------------
        # 绘制控制点和控制多边形
        # ti.GUI 的坐标也是 [0, 1]
        # ----------------------------------------------------
        if current_count > 0:
            pts_np = np.array(control_points, dtype=np.float32)

            # 控制多边形
            if current_count >= 2:
                for i in range(current_count - 1):
                    gui.line(
                        begin=control_points[i],
                        end=control_points[i + 1],
                        radius=2,
                        color=0x888888
                    )

            # 控制点
            for p in pts_np:
                gui.circle(
                    pos=(p[0], p[1]),
                    radius=6,
                    color=0xFF0000
                )

        # 左上角状态文字
        mode_text = "B-Spline" if bspline_mode else "Bezier"
        aa_text = "AA ON" if antialias else "AA OFF"

        gui.text(
            content=f"Mode: {mode_text} | {aa_text} | Points: {current_count}",
            pos=(0.02, 0.96),
            color=0xFFFFFF
        )

        gui.text(
            content="LMB: add point | C: clear | B: switch mode | A: anti-alias",
            pos=(0.02, 0.92),
            color=0xFFFFFF
        )

        gui.show()


if __name__ == "__main__":
    main()
