import os

def fix_file(path):
    encodings = ['utf-8', 'gbk', 'utf-16', 'utf-16-le', 'utf-16-be', 'latin-1']
    content = None
    
    with open(path, 'rb') as f:
        content = f.read()
        
    for enc in encodings:
        try:
            text = content.decode(enc)
            # If we decoded it, let's check for some recognizable strings
            # If it's the wrong encoding, it might decode but look like gibberish
            # but for our purposes, if it decodes and we can find "Tool" or "import", it's likely correct enough to fix
            if 'import' in text or 'def ' in text or 'class ' in text:
                # Perform the import fix
                text = text.replace('from app.agents', 'from agents')
                
                with open(path, 'w', encoding='utf-8', newline='') as f:
                    f.write(text)
                print(f"Fixed (using {enc}): {path}")
                return
        except Exception:
            continue
    
    print(f"Failed to fix {path} even after trying all encodings.")

tools_dir = 'agents/tools'
for root, dirs, files in os.walk(tools_dir):
    for file in files:
        if file.endswith('.py'):
            fix_file(os.path.join(root, file))
