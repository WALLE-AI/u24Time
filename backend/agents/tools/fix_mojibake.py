import os

directory = r"d:\LLM\project\WALL-AI\u24Time\backend\agents\tools"

def fix_mojibake(filepath):
    with open(filepath, 'rb') as f:
        content = f.read()
    
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        return False
        
    try:
        # Check if it has suspicious characters like '�'
        if '�' in text or '�' in text or '�' in text or '�' in text or '�' in text or '�' in text or '�' in text:
            # Try to reverse the mis-encoding
            # This happens if a utf-8 file was read as cp1252 and saved as utf-8
            fixed_bytes = text.encode('cp1252')
            fixed_text = fixed_bytes.decode('utf-8')
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(fixed_text)
            print(f"Fixed: {os.path.basename(filepath)}")
            return True
    except (UnicodeEncodeError, UnicodeDecodeError) as e:
        # Maybe not all text was cp1252 mis-encoded, or it's a mix.
        # Let's try gbk?
        try:
            fixed_bytes_gbk = text.encode('gbk')
            fixed_text_gbk = fixed_bytes_gbk.decode('utf-8')
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(fixed_text_gbk)
            print(f"Fixed (from gbk): {os.path.basename(filepath)}")
            return True
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
            
    return False

for filename in os.listdir(directory):
    if filename.endswith(".py"):
        filepath = os.path.join(directory, filename)
        fix_mojibake(filepath)
