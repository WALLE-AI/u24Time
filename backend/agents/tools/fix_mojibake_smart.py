import os
import re

directory = r"d:\LLM\project\WALL-AI\u24Time\backend\agents\tools"

def fix_smart(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()

    # check if mojibake chars exist
    mojibake_chars = ['�', '�', '�', '�', '�', '�', '�', '�', '�', '�', '�', '�', '�', '�']
    if not any(c in text for c in mojibake_chars):
        return False

    def replacer(match):
        s = match.group(0)
        # only process if it contains high-ascii characters
        if any(ord(c) >= 128 for c in s):
            try:
                b = s.encode('cp1252')
                decoded = b.decode('utf-8', errors='replace')
                # Optional: if it resolves to mostly legit characters, return it
                return decoded
            except UnicodeEncodeError:
                # Try latin-1 if cp1252 fails (cp1252 doesn't map 0x81, 0x8d, etc)
                try:
                    b = s.encode('latin-1')
                    return b.decode('utf-8', errors='replace')
                except Exception:
                    return s
        return s

    # Regex matches blocks of characters that are strictly <= 0xFF (Latin-1/ASCII)
    # We want to match as much as possible so that we don't split multibyte sequences
    new_text = re.sub(r'[\x00-\xff]+', replacer, text)
    
    if new_text != text:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_text)
        print(f"Fixed smart: {os.path.basename(filepath)}")
        return True
    return False

for filename in os.listdir(directory):
    if filename.endswith(".py"):
        filepath = os.path.join(directory, filename)
        fix_smart(filepath)
