import urllib.request
import json

try:
    res = urllib.request.urlopen('http://127.0.0.1:5001/api/v1/newsflash?domain=economy')
    print("ECONOMY:")
    print(json.loads(res.read()))
    
    res = urllib.request.urlopen('http://127.0.0.1:5001/api/v1/newsflash?domain=technology')
    print("\nTECHNOLOGY:")
    print(json.loads(res.read()))
except Exception as e:
    print("Error:", e)
