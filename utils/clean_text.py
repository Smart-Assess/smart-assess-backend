import re


def clean_and_tokenize_text(data):
    cleaned_texts = ""

    for point in data.points:
        if "text" in point.payload:
            raw_text = point.payload["text"]

            cleaned_text = re.sub(r"[●■○]", "", raw_text)
            cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()

            tokens = cleaned_text.split()

            filtered_tokens = [token.lower() for token in tokens if token.isalnum()]

            cleaned_text = " ".join(filtered_tokens)

            cleaned_texts += cleaned_text

    return cleaned_texts
