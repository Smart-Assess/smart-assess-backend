import requests
import re
import time

API_URL = "https://api-inference.huggingface.co/models/samadpls/t5-base-grammar-checker"
HEADERS = {"Authorization": "Bearer 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"}
MAX_CHUNK_SIZE = 10

class GrammarChecker:
    def __init__(self):
        self.api_url = API_URL
        self.headers = HEADERS
        self.max_chunk_size = MAX_CHUNK_SIZE

    def query(self, payload):
        """Send a request to the Hugging Face API and handle errors."""
        try:
            response = requests.post(self.api_url, headers=self.headers, json=payload)
            if response.status_code != 200:
                print(f"⚠️ API Error: {response.status_code} - {response.text}")
                return None  
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Request Failed: {e}")
            return None

    def split_text(self, text, chunk_size=MAX_CHUNK_SIZE):
        """
        Splits text into smaller parts:
        1. First, it splits by sentence boundaries.
        2. If a sentence is still too long, it further splits by words.
        """
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        for sentence in sentences:
            words = sentence.split()
            if len(words) > chunk_size:
                for i in range(0, len(words), chunk_size):
                    chunks.append(" ".join(words[i:i + chunk_size]))
            else:
                chunks.append(sentence)
        
        return chunks

    def correct_text(self, text):
        """Correct the grammar of the given text."""
        chunks = self.split_text(text)
        corrected_chunks = []
        for chunk in chunks:
            response = self.query({"inputs": f"grammar: {chunk}"})
            
            if response and isinstance(response, list) and "generated_text" in response[0]:  
                corrected_chunks.append(response[0]["generated_text"])
            else:
                corrected_chunks.append(chunk)
            
            time.sleep(0.5) 

        final_text = " ".join(corrected_chunks)
        return final_text

    def calculate_grammar_score(self, original_text, corrected_text):
        """Calculate a grammar score based on the difference between the original and corrected text."""
        original_words = set(original_text.split())
        corrected_words = set(corrected_text.split())
        common_words = original_words.intersection(corrected_words)
        score = len(common_words) / len(original_words) if original_words else 0
        return round(score, 4)

    def evaluate(self, text):
        corrected_text = self.correct_text(text)
        score = self.calculate_grammar_score(text, corrected_text)
        return corrected_text, score
    
if __name__ == "__main__":
    text = """This paragraph is very long and it have many mistake that makes hard to reading properly. People who writes sentence like this often do not realizes their error, but it are important to learn how to fix because bad grammar can making understanding difficult. Sometime, peoples dont even notice when they writing incorrect, but other time, it be very obvious and make confuse."""

    grammar_checker = GrammarChecker()
    corrected_text, score = grammar_checker.evaluate(text)

    print("Original Text:\n", text)
    print("\nCorrected Text:\n", corrected_text)
    print("\nGrammar Score:", score)