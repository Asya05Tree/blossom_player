import os
from PIL import Image, ImageDraw

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = os.path.join(root, "assets", "icon.png")
os.makedirs(os.path.dirname(path), exist_ok=True)
img = Image.new("RGB", (256, 256), "#F3E5F5")
draw = ImageDraw.Draw(img)
draw.ellipse((48, 48, 208, 208), fill="#D1C4E9", outline="#B39DDB", width=4)
draw.ellipse((98, 98, 158, 158), fill="#B39DDB")
img.save(path)
