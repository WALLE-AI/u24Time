import json
from data_alignment.pipeline import AlignmentPipeline
from loguru import logger

hf_rows = json.load(open("hf.json"))
if isinstance(hf_rows, dict): hf_rows = [hf_rows]

pipeline = AlignmentPipeline()
items = pipeline.align("academic.huggingface.papers", hf_rows)
print("Aligned Items for HF:", len(items))

