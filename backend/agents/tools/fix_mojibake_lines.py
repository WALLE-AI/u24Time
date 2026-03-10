import os
import sys

directory = r"d:\LLM\project\WALL-AI\u24Time\backend\agents\tools"

def fix_mojibake(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()

    # check if '�' is in text to quick filter
    if '�' not in text and '�' not in text:
        return False

    try:
        # Try converting the whole text back to bytes using cp1252
        # If the file has valid utf-8 that was NOT mojibaked, encode('cp1252') might throw exception.
        
        # A safer approach: parse line by line, or only replace the docstrings.
        # But let's try just line by line
        fixed_lines = []
        changed = False
        for line in text.splitlines(keepends=True):
            if '�' in line or '�' in line or '�' in line or '�' in line:
                try:
                    fixed_bytes = line.encode('cp1252')
                    fixed_line = fixed_bytes.decode('utf-8')
                    fixed_lines.append(fixed_line)
                    changed = True
                except (UnicodeEncodeError, UnicodeDecodeError) as e:
                    # fallback to whole file being cp1252 with string replace
                    # If this line has real unicode AND mojibake, we might need latin-1
                    try:
                        b = line.encode('latin-1')
                        fixed_line = b.decode('utf-8')
                        fixed_lines.append(fixed_line)
                        changed = True
                    except Exception as e:
                        print(f"Failed line in {os.path.basename(filepath)}: {e}")
                        fixed_lines.append(line)
            else:
                fixed_lines.append(line)
                
        if changed:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(''.join(fixed_lines))
            print(f"Fixed line-by-line: {os.path.basename(filepath)}")
            return True
    except Exception as e:
        print(f"Error processing {os.path.basename(filepath)}: {e}")
    return False

for filename in os.listdir(directory):
    if filename.endswith(".py"):
        filepath = os.path.join(directory, filename)
        fix_mojibake(filepath)
