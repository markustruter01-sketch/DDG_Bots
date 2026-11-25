import sys
from pathlib import Path
from PIL import Image

def convert():
    src = Path("C:/Users/User/Desktop/DDG/DDG_Local_Bot_Studio/assets/DDG_Logo_New.png")
    dst = Path("C:/Users/User/Desktop/DDG/DDG_Local_Bot_Studio/assets/app_icon.ico")
    if not src.exists():
        print("Source PNG not found.")
        return
    img = Image.open(src)
    # Save with multiple icon sizes for crisp Windows rendering
    icon_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(dst, format="ICO", sizes=icon_sizes)
    print(f"Created ICO at {dst}")

if __name__ == "__main__":
    convert()
