import json
from data_alignment.normalizers.academic_normalizer import academic_normalizer

hf = json.load(open("hf.json"))
try:
    item = academic_normalizer.normalize_huggingface_paper(hf)
    print("HF Normalizer output:", type(item), item)
except Exception as e:
    import traceback
    traceback.print_exc()

poly = json.load(open("poly.json"))
try:
    item = academic_normalizer.normalize_polymarket(poly)
    print("Poly Normalizer output:", type(item), item)
except Exception as e:
    import traceback
    traceback.print_exc()
