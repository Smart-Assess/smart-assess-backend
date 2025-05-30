import os
import time
import random
import requests
import re
import logging

logger = logging.getLogger(__name__)


class GrammarChecker:
    def __init__(self):
        self.api_url = os.getenv(
            "GRAMMAR_API_URL", "https://grammar-api.example.com/v1/check"
        )
        self.api_tokens = os.getenv("GRAMMAR_API_TOKENS", "").split(",")
        if not all(self.api_tokens) or not self.api_tokens[0]:
            logger.error("Grammar API tokens are not configured properly.")
            self.api_tokens = []

        self.current_token_index = 0
        self.headers = {}
        if self.api_tokens:
            self.headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_tokens[0]}",
            }
        self.max_retries = len(self.api_tokens) if self.api_tokens else 1
        self.service_available = True if self.api_tokens else False

    def _rotate_token(self):
        if not self.api_tokens or len(self.api_tokens) == 0:
            self.service_available = False
            return
        self.current_token_index = (self.current_token_index + 1) % len(self.api_tokens)
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_tokens[self.current_token_index]}",
        }
        logger.info(f"Switched to API token index {self.current_token_index}")

    def query_api(self, text, attempt=0, delay=0):
        if not self.service_available:
            logger.warning("Grammar service unavailable at query_api entry.")
            return None

        if attempt >= self.max_retries:
            logger.warning("Maximum retries reached for grammar API.")
            self.service_available = False
            return None

        if delay > 0 and attempt == 0:
            logger.info(f"Applying rate limiting delay: {delay} seconds")
            time.sleep(delay)

        try:
            payload = {"inputs": text}
            logger.info(
                f"Sending grammar API request for text length: {len(text)} with token index {self.current_token_index}"
            )
            response = requests.post(
                self.api_url, headers=self.headers, json=payload, timeout=10
            )
            logger.info(f"Grammar API response status: {response.status_code}")

            if response.status_code == 200:
                try:
                    result = response.json()
                    logger.info(f"Grammar API success - response type: {type(result)}")
                    self.service_available = True
                    return result
                except ValueError as e:
                    logger.error(f"Invalid JSON response from grammar API: {e}")
                    self.service_available = False
                    return None
            elif response.status_code in [503, 429, 401, 500, 502, 504]:
                logger.warning(
                    f"Grammar API returned {response.status_code}, rotating token and retrying"
                )
                time.sleep(1)
                self._rotate_token()
                if attempt + 1 < self.max_retries:
                    return self.query_api(text, attempt + 1, 0)
                else:
                    self.service_available = False
                    return None
            else:
                error_preview = (
                    response.text[:200] if response.text else "No error text"
                )
                logger.error(f"API Error: {response.status_code} - {error_preview}")
                if "<html" in error_preview.lower():
                    logger.warning(
                        "HTML error response detected, assuming service unavailable"
                    )
                self.service_available = False
                return None
        except requests.exceptions.Timeout:
            logger.error("Grammar API request timed out")
            self.service_available = False
            return None
        except requests.exceptions.ConnectionError:
            logger.error("Connection error to grammar API")
            self.service_available = False
            return None
        except Exception as e:
            logger.error(f"Exception during grammar API call: {str(e)}")
            if attempt + 1 < self.max_retries:
                self._rotate_token()
                time.sleep(1)
                return self.query_api(text, attempt + 1, 0)
            self.service_available = False
            return None

    def _calculate_similarity(self, original, corrected):
        try:
            if not original or not corrected:
                return 0.0
            if original == corrected:
                return 1.0
            original_len = len(original)
            corrected_len = len(corrected)
            if original_len == 0 and corrected_len == 0:
                return 1.0
            max_len = max(original_len, corrected_len)
            if max_len == 0:
                return 1.0
            matches = sum(
                1
                for i, char in enumerate(original)
                if i < len(corrected) and char == corrected[i]
            )
            similarity = matches / max_len
            return max(0.0, min(1.0, similarity))
        except Exception as e:
            logger.error(f"Error calculating similarity: {e}")
            return 0.0

    def _process_single_chunk(self, text, delay=0):
        if len(text.strip()) < 10:
            logger.info(f"Skipping tiny chunk: '{text[:20]}...'")
            return text, 1.0
        try:
            sanitized_text = text.encode("utf-8", "ignore").decode("utf-8")
        except:
            sanitized_text = text

        if not self.service_available:
            logger.warning("Grammar service unavailable before processing chunk.")
            return sanitized_text, None

        logger.info(f"Checking grammar for chunk with length {len(sanitized_text)}")
        result = self.query_api(sanitized_text, attempt=0, delay=delay)

        if result is None:
            logger.warning("Failed to get result from grammar API for chunk.")
            return sanitized_text, None
        try:
            if isinstance(result, list) and len(result) > 0:
                corrected_text = result[0].get("generated_text", sanitized_text)
            elif isinstance(result, dict):
                corrected_text = result.get("generated_text", sanitized_text)
            else:
                logger.warning(
                    f"Unexpected grammar API response format: {type(result)} - {result}"
                )
                return sanitized_text, None

            similarity = self._calculate_similarity(sanitized_text, corrected_text)
            grammar_score = max(0.0, min(1.0, similarity))
            logger.info(
                f"Grammar score for chunk: {grammar_score} (similarity: {similarity})"
            )
            return corrected_text, grammar_score
        except Exception as e:
            logger.error(f"Error processing grammar API result: {e}")
            return sanitized_text, None

    def evaluate_batch(self, texts_dict, delay=0):
        logger.info(f"Starting batch grammar evaluation for {len(texts_dict)} texts")
        results = {}
        short_texts = {}
        long_texts = {}

        for key, text in texts_dict.items():
            if not text or len(text.strip()) < 3:
                logger.info(f"Skipping empty/short text for {key}")
                results[key] = (text, 0.0)
                continue
            if not self.service_available:
                logger.info(f"Grammar service unavailable, returning None for {key}")
                results[key] = (text, None)
                continue
            if len(text) <= 90:
                short_texts[key] = text
            else:
                long_texts[key] = text

        for i, (key, text) in enumerate(short_texts.items()):
            actual_delay = delay if i > 0 else 0
            logger.info(f"Processing short text {key} with delay: {actual_delay}")
            corrected, score = self._process_single_chunk(text, actual_delay)
            results[key] = (corrected, score)

        for i, (key, text) in enumerate(long_texts.items()):
            actual_delay = delay * 0.5 if i > 0 else 0
            logger.info(f"Processing long text {key} with delay: {actual_delay}")
            corrected, score = self.evaluate(text, actual_delay)
            results[key] = (corrected, score)
        logger.info(
            f"Completed batch grammar evaluation, processed {len(results)} texts"
        )
        return results

    def evaluate(self, text, delay=0):
        if not text or len(text.strip()) < 3:
            logger.info("Empty or very short answer - assigning zero grammar score")
            return text, 0.0
        if not self.service_available:
            logger.info("Grammar service unavailable, returning None for score")
            return text, None

        MAX_CHUNK_SIZE = 500
        if len(text) <= MAX_CHUNK_SIZE:
            logger.info(f"Processing single chunk with delay: {delay}")
            return self._process_single_chunk(text, delay)

        logger.info(
            f"Text length {len(text)} exceeds chunk size, using optimized chunking"
        )
        chunks = self._smart_split(text, MAX_CHUNK_SIZE)
        logger.info(f"Split text into {len(chunks)} optimized chunks")
        all_scores = []
        all_lengths = []
        corrected_chunks = []
        any_chunk_failed = False

        for i, chunk in enumerate(chunks):
            chunk_delay = delay if i > 0 else 0
            corrected_chunk, chunk_score = self._process_single_chunk(
                chunk, chunk_delay
            )
            if chunk_score is None:
                any_chunk_failed = True
                logger.warning(
                    f"A chunk failed processing for text starting with: {text[:50]}..."
                )
                break
            corrected_chunks.append(corrected_chunk)
            all_scores.append(chunk_score)
            all_lengths.append(len(chunk))

        if any_chunk_failed:
            return text, None

        corrected_text = " ".join(corrected_chunks)
        if not all_scores:
            return text, None

        total_length = sum(all_lengths)
        if total_length == 0 and all_scores:
            weighted_score = sum(all_scores) / len(all_scores) if all_scores else None
        elif total_length > 0:
            weighted_score = sum(
                score * (length / total_length)
                for score, length in zip(all_scores, all_lengths)
            )
        else:  # No scores or no length
            weighted_score = None

        if weighted_score is not None:
            logger.info(
                f"Final weighted grammar score: {weighted_score} (from {len(all_scores)} chunks)"
            )
            return corrected_text, round(weighted_score, 4)
        else:
            logger.warning(
                f"Could not calculate weighted score for text: {text[:50]}..."
            )
            return corrected_text, None

    def _smart_split(self, text, max_size):
        if len(text) <= max_size:
            return [text]
        chunks = []
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        current_chunk = ""
        for paragraph in paragraphs:
            if len(current_chunk) + len(paragraph) + 2 > max_size:
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                current_chunk = ""
                if len(paragraph) > max_size:
                    sentences = self._split_by_sentences(paragraph, max_size)
                    chunks.extend(sentences)
                else:
                    current_chunk = paragraph
            else:
                if current_chunk:
                    current_chunk += "\n\n" + paragraph
                else:
                    current_chunk = paragraph
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        return self._merge_small_chunks(chunks, min_size=50)

    def _split_by_sentences(self, text, max_size):
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current_chunk = ""
        for sentence in sentences:
            if len(current_chunk) + len(sentence) + 1 > max_size:
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                current_chunk = ""
                if len(sentence) > max_size:
                    start = 0
                    while start < len(sentence):
                        chunks.append(sentence[start : start + max_size])
                        start += max_size
                else:
                    current_chunk = sentence
            else:
                if current_chunk:
                    current_chunk += " " + sentence
                else:
                    current_chunk = sentence
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        return chunks

    def _merge_small_chunks(self, chunks, min_size=50):
        if not chunks:
            return chunks
        merged = []
        current = ""
        for chunk_idx, chunk in enumerate(chunks):
            if len(current) == 0:
                current = chunk
            elif len(current) + len(chunk) + 1 <= 500:
                current += " " + chunk
            else:
                merged.append(current)
                current = chunk

            if chunk_idx == len(chunks) - 1 and current:
                merged.append(current)

        final_merged = []
        temp_chunk = ""
        for m_chunk in merged:
            if len(temp_chunk) == 0:
                temp_chunk = m_chunk
            elif len(m_chunk) < min_size and len(temp_chunk) + len(m_chunk) + 1 <= 500:
                temp_chunk += " " + m_chunk
            else:
                final_merged.append(temp_chunk)
                temp_chunk = m_chunk
        if temp_chunk:
            final_merged.append(temp_chunk)

        return [c for c in final_merged if c.strip()]


if __name__ == "__main__":
    grammar = GrammarChecker()
    test_text = """
                            Rain Cloud: A model where data is stored in natural clouds and accessed during rainfall.
Fire Cloud: Uses heat-based servers to process data faster.
Wind Cloud: Relies on wind patterns to transfer data wirelessly across continents.
Ghost Cloud: A stealth model where data is invisible to both users and providers, maximizing mystery over usability.
                            """
    data = grammar.evaluate(test_text, delay=0)
    print(f"Evaluation result: {data}")

    short_text = "This is a short sentenc."
    data_short = grammar.evaluate(short_text, delay=0)
    print(f"Evaluation result for short text: {data_short}")

    long_text = (
        "This is the first sentence of a very long paragraph that will definitely exceed the maximum chunk size. It continues on and on, with many words and phrases, to ensure that the splitting logic is thoroughly tested. We need to see how it handles multiple splits and merges. Another sentence follows, just to add more content. And one more for good measure, perhaps with a question mark at the end? Or an exclamation point! This should be sufficient."
        * 10
    )
    data_long = grammar.evaluate(long_text, delay=0)
    print(f"Evaluation result for long text: {data_long}")

    no_token_checker = GrammarChecker()
    no_token_checker.api_tokens = []
    no_token_checker.service_available = False
    data_no_token = no_token_checker.evaluate("Test text with no tokens configured.")
    print(f"Evaluation with no tokens: {data_no_token}")
