from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

here = Path(__file__).parent.parent.parent
source_path = here / "website/static/images/icon-app.png"
splash_path = here / "swiftcut_splash.png"

WIDTH, HEIGHT = 480, 320
ICON_SIZE = 160
BACKGROUND = (28, 30, 34)
TEXT_COLOR = (240, 240, 245, 255)

canvas = Image.new("RGBA", (WIDTH, HEIGHT), BACKGROUND + (255,))

icon = Image.open(source_path).convert("RGBA")
icon = icon.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
canvas.alpha_composite(icon, ((WIDTH - ICON_SIZE) // 2, 44))

try:
    font = ImageFont.truetype("segoeuib.ttf", 34)
except OSError:
    font = ImageFont.load_default()

draw = ImageDraw.Draw(canvas)
text = "SwiftCut"
box = draw.textbbox((0, 0), text, font=font)
draw.text(
    ((WIDTH - (box[2] - box[0])) // 2, 232), text, font=font, fill=TEXT_COLOR
)

canvas.convert("RGB").save(splash_path, format="PNG")
print("Splash generation complete.")
