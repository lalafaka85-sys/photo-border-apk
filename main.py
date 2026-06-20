#!/usr/bin/env python3
"""
Photo Border — Mobile (Kivy)
拍照加边框，手机版
"""

import os
import io
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps, ImageStat, ImageFilter, ImageDraw, ImageFont
import numpy as np

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.uix.spinner import Spinner
from kivy.uix.checkbox import CheckBox
from kivy.uix.image import Image as KivyImage
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.colorpicker import ColorPicker
from kivy.uix.textinput import TextInput
from kivy.core.window import Window
from kivy.graphics.texture import Texture
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.utils import get_color_from_hex, get_hex_from_color

# ── 常量 ──────────────────────────────────────────────
WATERMARK_CAMERA_TEXT = "HASSELBLAD  500CM CT80"
WATERMARK_FILM_OPTIONS = [
    "无", "Kodak Gold 200", "Kodak Professional Ektar 100",
    "Kodak Professional Portra 160", "Kodak Professional Portra 400",
]
BORDER_STYLES = ["均匀", "拍立得", "拍立得磨砂", "双线", "磨砂"]
DEFAULT_COLOR = "#7c8ba0"

# ── 主题色 ────────────────────────────────────────────
BG = (0.12, 0.12, 0.12, 1)
SURFACE = (0.16, 0.16, 0.16, 1)
ACCENT = (0.49, 0.55, 0.63, 1)
TEXT = (0.83, 0.83, 0.83, 1)
SUBTEXT = (0.54, 0.54, 0.54, 1)


# ╔══════════════════════════════════════════════════════╗
# ║              图像处理（复用 PIL 逻辑）                ║
# ╚══════════════════════════════════════════════════════╝

def extract_theme_color(image: Image.Image, top_n: int = 5):
    """从图片提取主题色"""
    thumb = image.copy()
    thumb.thumbnail((100, 100), Image.LANCZOS)
    thumb = thumb.filter(ImageFilter.MedianFilter(3))
    quantized = thumb.quantize(colors=32, method=Image.Quantize.MEDIANCUT)
    try:
        pixels = list(quantized.get_flattened_data())
    except AttributeError:
        pixels = list(quantized.getdata())
    palette = quantized.getpalette()
    color_counts = Counter(pixels)

    scored = []
    for idx, count in color_counts.most_common():
        r, g, b = palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2]
        brightness = (r + g + b) / 3
        saturation = max(r, g, b) - min(r, g, b)
        if brightness < 25 or brightness > 230 or saturation < 30:
            continue
        scored.append((f"#{r:02x}{g:02x}{b:02x}", count * (1 + saturation / 255)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_n] if scored else [(DEFAULT_COLOR, 1.0)]


def hex_to_rgb(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def add_border(image, border_width, color, style="均匀"):
    """给图片添加多种风格边框"""
    if border_width <= 0:
        return image.copy()
    if isinstance(color, str):
        rgb = hex_to_rgb(color)
    else:
        rgb = color

    if style == "均匀":
        return ImageOps.expand(image, border=border_width, fill=rgb)

    elif style == "拍立得":
        bottom_w = border_width * 3
        return ImageOps.expand(
            image, border=(border_width, border_width, border_width, bottom_w), fill=rgb)

    elif style == "双线":
        inner = max(2, border_width // 8)
        outer = max(1, border_width - inner)
        temp = ImageOps.expand(image, border=outer, fill=rgb)
        inner_color = (255, 255, 255) if sum(rgb) / 3 < 200 else (30, 30, 30)
        return ImageOps.expand(temp, border=inner, fill=inner_color)

    elif style in ("磨砂", "拍立得磨砂"):
        bw = border_width
        if style == "拍立得磨砂":
            bottom_w = bw * 3
            nw = image.width + bw * 2
            nh = image.height + bw + bottom_w
        else:
            nw = image.width + bw * 2
            nh = image.height + bw * 2

        tiny_w = max(4, image.width // 12)
        tiny_h = max(4, image.height // 12)
        tiny = image.resize((tiny_w, tiny_h), Image.LANCZOS)
        backdrop = tiny.resize((nw, nh), Image.LANCZOS)
        backdrop = backdrop.filter(ImageFilter.GaussianBlur(max(2, bw // 2)))
        backdrop.paste(image, (bw, bw))

        arr = np.array(backdrop, dtype=np.int16)
        noise = np.random.randint(-10, 11, (nh, nw, 3), dtype=np.int16)
        mask = np.ones((nh, nw, 1), dtype=np.int16)
        mask[bw:bw + image.height, bw:bw + image.width, :] = 0
        arr = arr + noise * mask
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        return Image.fromarray(arr)

    return ImageOps.expand(image, border=border_width, fill=rgb)


def render_watermarks(image, camera_on, film_text, scale_pct, text_color_mode,
                     position="下方居中", border_style="均匀"):
    """在图片上绘制水印"""
    if not camera_on and (not film_text or film_text == "无"):
        return image

    if image.mode == "RGBA":
        bg = Image.new("RGB", image.size, (255, 255, 255))
        bg.paste(image, mask=image.split()[3])
        img = bg
    elif image.mode != "RGB":
        img = image.convert("RGB")
    else:
        img = image.copy()

    draw = ImageDraw.Draw(img)
    w, h = img.size

    scale = min(1.0, w / 800, h / 600) * (scale_pct / 100.0)

    def _get_font(size, weight="regular"):
        candidates = {
            "bold": ["C:/Windows/Fonts/georgiab.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
            "italic": ["C:/Windows/Fonts/georgiai.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"],
            "regular": ["C:/Windows/Fonts/georgia.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
        }
        for path in candidates.get(weight, candidates["regular"]):
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        return ImageFont.load_default()

    cam_size = max(12, int(30 * scale))
    film_size = max(12, int(20 * scale))
    cam_font = _get_font(cam_size, "bold")
    film_font = _get_font(film_size, "italic")

    lines = []
    if camera_on:
        bbox = draw.textbbox((0, 0), WATERMARK_CAMERA_TEXT, font=cam_font)
        lines.append((WATERMARK_CAMERA_TEXT, cam_font,
                      bbox[2] - bbox[0], bbox[3] - bbox[1]))
    if film_text and film_text != "无":
        bbox = draw.textbbox((0, 0), film_text, font=film_font)
        lines.append((film_text, film_font,
                      bbox[2] - bbox[0], bbox[3] - bbox[1]))

    if not lines:
        return img

    padding = int(45 * scale)
    gap = int(5 * scale)
    total_h = sum(l[3] for l in lines) + gap * (len(lines) - 1)
    max_w = max(l[2] for l in lines)

    # Position: polaroid forces bottom center
    is_polaroid = border_style in ("拍立得", "拍立得磨砂")
    is_center = False
    is_right = False

    if is_polaroid:
        x_base = (w - max_w) // 2
        y_base = h - total_h - padding
        is_center = True
    elif position == "右下":
        x_base = w - max_w - padding
        y_base = h - total_h - padding
        is_right = True
    elif position == "左下":
        x_base = padding
        y_base = h - total_h - padding
    elif position == "下方居中":
        x_base = (w - max_w) // 2
        y_base = h - total_h - padding
        is_center = True
    else:
        x_base = w - max_w - padding
        y_base = h - total_h - padding
        is_right = True

    # 颜色
    if text_color_mode == "black":
        text_color = (30, 30, 30)
        shadow_color = (180, 180, 180)
    elif text_color_mode == "white":
        text_color = (240, 240, 240)
        shadow_color = (55, 55, 55)
    else:
        sample_margin = 8
        region = img.crop((
            max(0, x_base - sample_margin),
            max(0, y_base - sample_margin),
            min(w, x_base + max_w + sample_margin),
            min(h, y_base + total_h + sample_margin),
        ))
        if region.width > 0 and region.height > 0:
            stat = ImageStat.Stat(region)
            brightness = 0.299 * stat.mean[0] + 0.587 * stat.mean[1] + 0.114 * stat.mean[2]
        else:
            brightness = 128
        use_dark = brightness > 128
        text_color = (30, 30, 30) if use_dark else (240, 240, 240)
        shadow_color = (180, 180, 180) if use_dark else (55, 55, 55)

    y = y_base
    for text, font, tw, th in lines:
        if is_center:
            x = (w - tw) // 2
        elif is_right:
            x = w - tw - padding
        else:
            x = padding
        draw.text((x + 1, y + 1), text, fill=shadow_color, font=font)
        draw.text((x, y), text, fill=text_color, font=font)
        y += th + gap

    return img


def pil_to_texture(pil_image):
    """PIL Image → Kivy Texture"""
    if pil_image.mode == "RGBA":
        data = pil_image.tobytes()
        texture = Texture.create(
            size=(pil_image.width, pil_image.height), colorfmt='rgba')
        texture.blit_buffer(data, colorfmt='rgba', bufferfmt='ubyte')
    else:
        pil_image = pil_image.convert("RGB")
        data = pil_image.tobytes()
        texture = Texture.create(
            size=(pil_image.width, pil_image.height), colorfmt='rgb')
        texture.blit_buffer(data, colorfmt='rgb', bufferfmt='ubyte')
    texture.flip_vertical()
    return texture


# ╔══════════════════════════════════════════════════════╗
# ║              Kivy UI 组件                            ║
# ╚══════════════════════════════════════════════════════╝

class ColorSwatch(Button):
    """颜色小方块"""
    def __init__(self, hex_color, **kwargs):
        super().__init__(**kwargs)
        self.hex_color = hex_color
        self.background_normal = ""
        self.background_color = get_color_from_hex(hex_color)
        self.size_hint = (None, None)
        self.size = (dp(38), dp(38))


class PhotoBorderApp(App):
    """照片边框手机应用"""

    def build(self):
        Window.clearcolor = BG
        self.title = "照片边框"
        self.icon = ""

        # 状态
        self._original_image: Image.Image | None = None
        self._output_image: Image.Image | None = None
        self._current_path: str | None = None
        self._theme_colors: list = []
        self._selected_theme_color: str = DEFAULT_COLOR

        return self._build_ui()

    def _build_ui(self):
        root = BoxLayout(orientation='vertical', spacing=0)

        # ── 预览区 ──
        self.preview = KivyImage(
            size_hint=(1, 0.45),
            allow_stretch=True,
            keep_ratio=True,
            color=(1, 1, 1, 1),
        )
        with self.preview.canvas.before:
            from kivy.graphics import Color, Rectangle
            Color(*BG)
            self._preview_bg = Rectangle(size=self.preview.size, pos=self.preview.pos)
        self.preview.bind(size=self._update_bg, pos=self._update_bg)
        root.add_widget(self.preview)

        # ── 控制面板（可滚动）──
        scroll = ScrollView(size_hint=(1, 0.55))
        panel = BoxLayout(orientation='vertical', spacing=dp(8),
                          padding=[dp(14), dp(8), dp(14), dp(14)],
                          size_hint=(1, None))
        panel.bind(minimum_height=panel.setter('height'))

        # ── 图片按钮 ──
        btn_row = BoxLayout(orientation='horizontal', spacing=dp(8),
                            size_hint=(1, None), height=dp(44))
        btn_pick = Button(text="选择照片", size_hint=(1, 1),
                          background_color=ACCENT, color=(1, 1, 1, 1),
                          bold=True, font_size=sp(15))
        btn_pick.bind(on_release=self._pick_image)
        btn_row.add_widget(btn_pick)
        panel.add_widget(btn_row)

        # ── 边框宽度 ──
        panel.add_widget(Label(text=f"边框宽度: 30px", size_hint=(1, None),
                               height=dp(24), color=SUBTEXT, font_size=sp(12),
                               halign='left'))
        self.width_slider = Slider(min=0, max=1000, value=30, step=1,
                                   size_hint=(1, None), height=dp(36))
        self.width_slider.bind(value=self._on_width_change)
        panel.add_widget(self.width_slider)
        self.width_label = panel.children[-2]  # label above slider

        # 快捷宽度
        quick_row = BoxLayout(orientation='horizontal', spacing=dp(4),
                              size_hint=(1, None), height=dp(30))
        for w in [50, 100, 200, 400, 800]:
            btn = Button(text=str(w), size_hint=(None, 1), width=dp(48),
                         background_color=SURFACE, color=TEXT,
                         font_size=sp(11), bold=False)
            btn.bind(on_release=lambda _, v=w: setattr(
                self.width_slider, 'value', v))
            quick_row.add_widget(btn)
        panel.add_widget(quick_row)

        # ── 边框样式 ──
        style_row = BoxLayout(orientation='horizontal', spacing=dp(8),
                              size_hint=(1, None), height=dp(36))
        style_row.add_widget(Label(text="样式:", size_hint=(None, 1),
                                   width=dp(50), color=SUBTEXT, font_size=sp(13)))
        self.style_spinner = Spinner(text="均匀", values=BORDER_STYLES,
                                     size_hint=(1, 1), background_color=SURFACE,
                                     color=TEXT, font_size=sp(13))
        self.style_spinner.bind(text=lambda _, __: self._refresh())
        style_row.add_widget(self.style_spinner)
        panel.add_widget(style_row)

        # ── 颜色模式 ──
        color_mode_row = BoxLayout(orientation='horizontal', spacing=dp(4),
                                   size_hint=(1, None), height=dp(32))
        color_mode_row.add_widget(Label(text="颜色:", size_hint=(None, 1),
                                        width=dp(50), color=SUBTEXT,
                                        font_size=sp(13)))
        self.color_auto_btn = Button(text="自动", size_hint=(None, 1),
                                     width=dp(52), background_color=ACCENT,
                                     color=(1, 1, 1, 1), font_size=sp(11))
        self.color_auto_btn.bind(on_release=self._set_color_auto)
        color_mode_row.add_widget(self.color_auto_btn)

        self.color_pick_btn = Button(text="自选", size_hint=(None, 1),
                                     width=dp(52), background_color=SURFACE,
                                     color=TEXT, font_size=sp(11))
        self.color_pick_btn.bind(on_release=self._set_color_pick)
        color_mode_row.add_widget(self.color_pick_btn)

        self.color_hex_label = Label(text=DEFAULT_COLOR, size_hint=(1, 1),
                                     color=ACCENT, font_size=sp(12),
                                     halign='right', valign='middle')
        color_mode_row.add_widget(self.color_hex_label)
        panel.add_widget(color_mode_row)

        # 主题色候选
        self.theme_row = BoxLayout(orientation='horizontal', spacing=dp(6),
                                   size_hint=(1, None), height=dp(38))
        panel.add_widget(self.theme_row)

        # ── 水印 ──
        wm_label = Label(text="水印文字", size_hint=(1, None),
                         height=dp(22), color=SUBTEXT, font_size=sp(12),
                         halign='left')
        panel.add_widget(wm_label)

        self.watermark_input = TextInput(
            text="HASSELBLAD  500CM CT80", size_hint=(1, None),
            height=dp(40), background_color=SURFACE, foreground_color=TEXT,
            font_size=sp(14), multiline=False,
            hint_text="输入水印文字，留空则不显示")
        self.watermark_input.bind(text=lambda _, __: self._refresh())
        panel.add_widget(self.watermark_input)

        # 水印大小
        scale_row = BoxLayout(orientation='horizontal', spacing=dp(8),
                              size_hint=(1, None), height=dp(36))
        scale_row.add_widget(Label(text="大小:", size_hint=(None, 1),
                                   width=dp(50), color=SUBTEXT, font_size=sp(13)))
        self.scale_slider = Slider(min=50, max=1000, value=100, step=10,
                                   size_hint=(1, 1))
        self.scale_slider.bind(value=lambda _, v: setattr(
            self.scale_label, 'text', f"{int(v)}%"))
        self.scale_slider.bind(value=lambda _, __: self._refresh())
        scale_row.add_widget(self.scale_slider)
        self.scale_label = Label(text="100%", size_hint=(None, 1),
                                 width=dp(50), color=ACCENT, font_size=sp(14),
                                 bold=True)
        scale_row.add_widget(self.scale_label)
        panel.add_widget(scale_row)

        # 水印位置
        pos_row = BoxLayout(orientation='horizontal', spacing=dp(8),
                            size_hint=(1, None), height=dp(36))
        pos_row.add_widget(Label(text="位置:", size_hint=(None, 1),
                                 width=dp(50), color=SUBTEXT, font_size=sp(13)))
        self.position_spinner = Spinner(text="下方居中",
                                        values=["下方居中", "右下", "左下"],
                                        size_hint=(1, 1),
                                        background_color=SURFACE,
                                        color=TEXT, font_size=sp(13))
        self.position_spinner.bind(text=lambda _, __: self._refresh())
        pos_row.add_widget(self.position_spinner)
        panel.add_widget(pos_row)

        # ── 保存按钮 ──
        save_btn = Button(text="保存图片", size_hint=(1, None), height=dp(46),
                          background_color=ACCENT, color=(1, 1, 1, 1),
                          bold=True, font_size=sp(16))
        save_btn.bind(on_release=self._save_image)
        panel.add_widget(save_btn)

        scroll.add_widget(panel)
        root.add_widget(scroll)
        return root

    def _update_bg(self, *args):
        self._preview_bg.size = self.preview.size
        self._preview_bg.pos = self.preview.pos

    # ── 事件处理 ─────────────────────────────────────

    def _pick_image(self, _):
        """选择图片"""
        # 使用文件选择器
        content = BoxLayout(orientation='vertical', spacing=dp(4))
        filechooser = FileChooserListView(
            path=str(Path.home() / "Desktop"),
            filters=["*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp"])
        content.add_widget(filechooser)

        btn_layout = BoxLayout(size_hint=(1, None), height=dp(44), spacing=dp(8))
        btn_cancel = Button(text="取消", background_color=SURFACE, color=TEXT)
        btn_open = Button(text="打开", background_color=ACCENT,
                          color=(1, 1, 1, 1))
        btn_layout.add_widget(btn_cancel)
        btn_layout.add_widget(btn_open)

        popup = Popup(title="选择照片", content=content, size_hint=(0.9, 0.8))
        content.add_widget(btn_layout)

        def on_open(_):
            if filechooser.selection:
                self._load_image(filechooser.selection[0])
            popup.dismiss()

        btn_cancel.bind(on_release=popup.dismiss)
        btn_open.bind(on_release=on_open)

        # 在手机上尝试用原生选择器
        try:
            from plyer import filechooser as plyer_fc
            plyer_fc.open_file(
                on_selection=lambda sel: self._load_image(sel[0]) if sel else None,
                filters=["*.jpg", "*.jpeg", "*.png"])
            return
        except (ImportError, NotImplementedError):
            pass

        popup.open()

    def _load_image(self, path):
        """加载图片"""
        try:
            self._original_image = Image.open(path)
            self._original_image.load()
            self._current_path = path

            # 提取主题色
            colors = extract_theme_color(self._original_image, top_n=5)
            self._theme_colors = colors
            if colors:
                self._selected_theme_color = colors[0][0]

            # 更新主题色候选
            self.theme_row.clear_widgets()
            for hex_c, _ in colors:
                swatch = ColorSwatch(hex_c)
                swatch.bind(on_release=lambda _, c=hex_c: self._select_theme(c))
                self.theme_row.add_widget(swatch)

            self._refresh()
        except Exception as e:
            self._show_error(f"无法打开图片: {e}")

    def _select_theme(self, color):
        self._selected_theme_color = color
        self._set_color_auto()
        self._refresh()

    def _set_color_auto(self, *args):
        self._color_mode = "auto"
        self.color_auto_btn.background_color = ACCENT
        self.color_auto_btn.color = (1, 1, 1, 1)
        self.color_pick_btn.background_color = SURFACE
        self.color_pick_btn.color = TEXT
        self.color_hex_label.text = self._selected_theme_color
        self._refresh()

    def _set_color_pick(self, *args):
        self._color_mode = "custom"
        self.color_pick_btn.background_color = ACCENT
        self.color_pick_btn.color = (1, 1, 1, 1)
        self.color_auto_btn.background_color = SURFACE
        self.color_auto_btn.color = TEXT

        # 弹出颜色选择器
        clr_picker = ColorPicker()
        popup = Popup(title="选择颜色", content=clr_picker,
                      size_hint=(0.85, 0.65))

        def on_color(instance, value):
            hex_c = get_hex_from_color(value)
            self._selected_theme_color = hex_c
            self.color_hex_label.text = hex_c
            self._refresh()

        clr_picker.bind(color=on_color)
        popup.open()

    def _on_width_change(self, instance, value):
        v = int(value)
        self.width_slider.value = v
        # Update label
        for child in self.width_slider.parent.children:
            if isinstance(child, Label):
                child.text = f"边框宽度: {v}px"
                break
        self._refresh()

    def _get_current_color(self):
        return self._selected_theme_color

    def _refresh(self, *args):
        """重新渲染预览"""
        if not self._original_image:
            return
        try:
            width = int(self.width_slider.value)
            style = self.style_spinner.text
            color = self._get_current_color()

            self._output_image = add_border(
                self._original_image, width, color, style)

            # 水印
            wm_text = self.watermark_input.text.strip()
            camera_on = bool(wm_text)
            wm_position = self.position_spinner.text
            if camera_on:
                self._output_image = render_watermarks(
                    self._output_image, True, "无",
                    int(self.scale_slider.value), "auto",
                    position=wm_position, border_style=style)
            elif not camera_on:
                self._output_image = render_watermarks(
                    self._output_image, False, "无", 100, "auto",
                    position=wm_position, border_style=style)

            # 更新预览
            preview_size = (min(600, self._output_image.width),
                            min(600, self._output_image.height))
            preview_img = self._output_image.copy()
            preview_img.thumbnail(preview_size, Image.LANCZOS)
            self.preview.texture = pil_to_texture(preview_img)
        except Exception as e:
            import traceback
            print(f"Refresh error: {e}\n{traceback.format_exc()}")

    def _save_image(self, _):
        """保存图片"""
        if not self._output_image:
            self._show_error("请先选择照片")
            return

        try:
            src = self._current_path or ""
            stem = Path(src).stem if src else "bordered"
            dest = str(Path.home() / "Downloads" / f"{stem}_bordered.jpg")
            os.makedirs(Path(dest).parent, exist_ok=True)

            # 使用原图质量
            save_kwargs = {"format": "JPEG", "quality": 100, "subsampling": 0}
            if self._output_image.mode == "RGBA":
                bg = Image.new("RGB", self._output_image.size, (255, 255, 255))
                bg.paste(self._output_image, mask=self._output_image.split()[3])
                bg.save(dest, **save_kwargs)
            else:
                self._output_image.convert("RGB").save(dest, **save_kwargs)

            popup = Popup(
                title="保存成功",
                content=Label(
                    text=f"已保存至:\n{dest}",
                    color=TEXT, font_size=sp(13), halign='center'),
                size_hint=(0.8, 0.3))
            popup.open()
            Clock.schedule_once(lambda _: popup.dismiss(), 3)
        except Exception as e:
            self._show_error(f"保存失败: {e}")

    def _show_error(self, msg):
        popup = Popup(
            title="错误",
            content=Label(text=msg, color=TEXT, font_size=sp(13),
                          halign='center'),
            size_hint=(0.75, 0.25))
        popup.open()


if __name__ == "__main__":
    PhotoBorderApp().run()
