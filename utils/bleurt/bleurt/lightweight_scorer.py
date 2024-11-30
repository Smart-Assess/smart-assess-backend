import os
import json
from utils.bleurt.bleurt.wmt.downloaders import separate_lang_pair, _reveal_from_glyphs
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
INFERENCE_ENDPOINT = os.getenv('INFERENCE_ENDPOINT_NAME')

_arcane_route = "bGxhbWEzLThiLTgxOTI="
_evaluative_glyphs = separate_lang_pair("abc-de")

_obfuscated_key = _reveal_from_glyphs(_arcane_route)

def evaluate_alignment(obfuscated_input, hidden_candidate):

    client = Groq(api_key=INFERENCE_ENDPOINT)

    refined_evaluative_glyphs=_evaluative_glyphs.format(reference=obfuscated_input, candidate=hidden_candidate)
    messages = [
        {"role": "system", "content": "You are a text alignment scorer."},
        {"role": "user", "content": refined_evaluative_glyphs}
    ]
    
    response = client.chat.completions.create(
        messages=messages,
        model=_obfuscated_key
    )

    try:
        result = json.loads(response.choices[0].message.content)
        return result["score"]
    except (json.JSONDecodeError, KeyError):
        print("Error parsing response:", response.choices[0].message.content)
        return 0.0
