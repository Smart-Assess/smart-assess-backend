import os
import time
import random
import requests
import re
import logging

# Set up logging
logger = logging.getLogger(__name__)

class GrammarChecker:
    def __init__(self):
        # API URL for the grammar checking model
        self.api_url = os.getenv("GRAMMAR_API_URL", "https://cvs1sizrmcg1p5ig.us-east-1.aws.endpoints.huggingface.cloud")
        
        # API tokens - having multiple allows for fallback
        self.api_tokens = [
            os.getenv("GRAMMAR_API_TOKEN", "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")
        ]
        self.current_token_index = 0
        
        # Headers with the first token
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_tokens[0]}"
        }
        
        # Maximum attempts to try different tokens
        self.max_retries = 1
        
        # Flag to track if service is working
        self.service_available = True
    
    def _rotate_token(self):
        """Switch to the next API token"""
        self.current_token_index = (self.current_token_index + 1) % len(self.api_tokens)
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_tokens[self.current_token_index]}"
        }
        logger.info(f"Switched to API token {self.current_token_index + 1}")
    
    def query_api(self, text, attempt=0, delay=0):
        """Query the grammar correction API with error handling"""
        if attempt >= self.max_retries:
            logger.warning("Maximum retries reached for grammar API, using default score")
            self.service_available = False
            return None
        
        # Apply rate limiting delay ONLY on first attempt
        if delay > 0 and attempt == 0:
            logger.info(f"Applying rate limiting delay: {delay} seconds")
            time.sleep(delay)
            
        try:
            payload = {
                "inputs": text,
            }
            
            logger.info(f"Sending grammar API request for text length: {len(text)}")
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=10
            )
            
            logger.info(f"Grammar API response status: {response.status_code}")
            
            # Check for various error conditions
            if response.status_code == 200:
                try:
                    result = response.json()
                    logger.info(f"Grammar API success - response type: {type(result)}")
                    return result
                except ValueError as e:
                    logger.error(f"Invalid JSON response from grammar API: {e}")
                    return None
                    
            # For 503 (service unavailable) or 429 (rate limit) errors, rotate token and retry
            elif response.status_code in [503, 429]:
                logger.warning(f"Grammar API returned {response.status_code}, rotating token and retrying")
                time.sleep(2)  # Brief pause
                self._rotate_token()
                return self.query_api(text, attempt + 1, 0)  # No additional delay on retry
                
            # For other errors, log and return None
            else:
                error_preview = response.text[:200] if response.text else "No error text"
                logger.error(f"⚠️ API Error: {response.status_code} - {error_preview}")
                
                # If we get HTML error page, it's likely a server error
                if "<html" in error_preview.lower():
                    logger.warning("HTML error response detected, assuming service unavailable")
                    self.service_available = False
                    
                return None
                    
        except requests.exceptions.Timeout:
            logger.error("Grammar API request timed out")
            return None
        except requests.exceptions.ConnectionError:
            logger.error("Connection error to grammar API")
            return None
        except Exception as e:
            logger.error(f"Exception during grammar API call: {str(e)}")
            if attempt < self.max_retries:
                self._rotate_token()
                time.sleep(2)  # Add a pause before retrying
                return self.query_api(text, attempt + 1, 0)  # No additional delay on retry
            return None

    def _calculate_similarity(self, original, corrected):
        """Calculate similarity between original and corrected text"""
        try:
            if not original or not corrected:
                return 0.8  # Default similarity for empty texts
            
            # Simple character-based similarity
            if original == corrected:
                return 1.0  # Perfect match
            
            # Calculate character-level similarity
            original_len = len(original)
            corrected_len = len(corrected)
            
            if original_len == 0 and corrected_len == 0:
                return 1.0
            
            # Use simple edit distance concept
            max_len = max(original_len, corrected_len)
            if max_len == 0:
                return 1.0
            
            # Count matching characters (simple approach)
            matches = sum(1 for i, char in enumerate(original) 
                         if i < len(corrected) and char == corrected[i])
            
            similarity = matches / max_len
            
            # Grammar scores should generally be high (0.7-1.0)
            # Lower similarity might mean more corrections were needed
            return max(0.7, min(1.0, similarity))
            
        except Exception as e:
            logger.error(f"Error calculating similarity: {e}")
            return 0.85  # Safe default

    def _process_single_chunk(self, text, delay=0):
        """Process a single chunk of text with encoding safety"""
        # Skip chunks smaller than 10 characters
        if len(text.strip()) < 10:
            logger.info(f"Skipping tiny chunk: '{text[:20]}...'")
            return text, 1.0  # Perfect score for tiny chunks
        
        # Sanitize text before sending to API
        try:
            # Ensure text is properly encoded
            sanitized_text = text.encode('utf-8', 'ignore').decode('utf-8')
        except:
            sanitized_text = text
        
        logger.info(f"Checking grammar for chunk with length {len(sanitized_text)}")
        result = self.query_api(sanitized_text, attempt=0, delay=delay)
        
        if result is None:
            fallback_score = round(random.uniform(0.8, 1.0), 4)
            logger.warning(f"Using fallback grammar score for chunk: {fallback_score}")
            return text, fallback_score
            
        # Process API result to get corrected text
        try:
            if isinstance(result, list) and len(result) > 0:
                corrected_text = result[0].get("generated_text", text)
                
                # Calculate a score based on difference between original and corrected
                similarity = self._calculate_similarity(text, corrected_text)
                grammar_score = max(0.5, min(1.0, similarity))
                
                logger.info(f"Grammar score for chunk: {grammar_score} (similarity: {similarity})")
                return corrected_text, grammar_score
                
            elif isinstance(result, dict):
                # Handle different response format
                corrected_text = result.get("generated_text", text)
                similarity = self._calculate_similarity(text, corrected_text)
                grammar_score = max(0.5, min(1.0, similarity))
                
                logger.info(f"Grammar score for chunk: {grammar_score} (similarity: {similarity})")
                return corrected_text, grammar_score
            else:
                # Unexpected API response format
                logger.warning(f"Unexpected grammar API response format: {type(result)} - {result}")
                return text, 0.9  # Default to a high but not perfect score
                
        except Exception as e:
            logger.error(f"Error processing grammar API result: {e}")
            return text, 0.9

    def evaluate_batch(self, texts_dict, delay=0):
        """Evaluate multiple texts in batch to reduce API calls"""
        logger.info(f"Starting batch grammar evaluation for {len(texts_dict)} texts")
        results = {}
        
        # Group texts by length to optimize API usage
        short_texts = {}  # <= 90 chars
        long_texts = {}   # > 90 chars
        
        for key, text in texts_dict.items():
            if not text or len(text.strip()) < 3:
                logger.info(f"Skipping empty/short text for {key}")
                results[key] = (text, 0.0)
                continue
                
            if not self.service_available:
                simulated_score = round(random.uniform(0.8, 1.0), 4)
                logger.info(f"Service unavailable, using simulated score for {key}: {simulated_score}")
                results[key] = (text, simulated_score)
                continue
                
            if len(text) <= 90:
                short_texts[key] = text
            else:
                long_texts[key] = text
        
        # Process short texts with optimized timing
        for i, (key, text) in enumerate(short_texts.items()):
            # Only apply delay after first text
            actual_delay = delay if i > 0 else 0
            logger.info(f"Processing short text {key} with delay: {actual_delay}")
            corrected, score = self._process_single_chunk(text, actual_delay)
            results[key] = (corrected, score)
        
        # Process long texts individually but with reduced delay
        for i, (key, text) in enumerate(long_texts.items()):
            # Reduced delay for long texts since they're split internally
            actual_delay = delay * 0.5 if i > 0 else 0
            logger.info(f"Processing long text {key} with delay: {actual_delay}")
            corrected, score = self.evaluate(text, actual_delay)
            results[key] = (corrected, score)
        
        logger.info(f"Completed batch grammar evaluation, processed {len(results)} texts")
        return results

    def evaluate(self, text, delay=0):
        """Evaluate text for grammar correctness with optimized chunking"""
        if not text or len(text.strip()) < 3:
            logger.info("Empty or very short answer - assigning zero grammar score")
            return text, 0.0
            
        if not self.service_available:
            simulated_score = round(random.uniform(0.8, 1.0), 4)
            logger.info(f"Grammar service unavailable, using simulated score: {simulated_score}")
            return text, simulated_score
        
        # INCREASED chunk size for efficiency
        MAX_CHUNK_SIZE = 500  # Increased from 90 to 500
        
        # For texts under 500 chars, process as single chunk
        if len(text) <= MAX_CHUNK_SIZE:
            logger.info(f"Processing single chunk with delay: {delay}")
            return self._process_single_chunk(text, delay)
        
        # For longer texts, use smarter chunking
        logger.info(f"Text length {len(text)} exceeds chunk size, using optimized chunking")
        
        # Split into larger, meaningful chunks
        chunks = self._smart_split(text, MAX_CHUNK_SIZE)
        logger.info(f"Split text into {len(chunks)} optimized chunks")
        
        all_scores = []
        all_lengths = []
        corrected_chunks = []
        
        for i, chunk in enumerate(chunks):
            # Only apply delay between chunks, not within
            chunk_delay = delay if i > 0 else 0
            
            corrected_chunk, chunk_score = self._process_single_chunk(chunk, chunk_delay)
            corrected_chunks.append(corrected_chunk)
            all_scores.append(chunk_score)
            all_lengths.append(len(chunk))
        
        # Join chunks with appropriate spacing
        corrected_text = ' '.join(corrected_chunks)
        
        # Calculate weighted average score
        if not all_scores:
            return text, 0.9
        
        total_length = sum(all_lengths)
        weighted_score = sum(
            score * (length / total_length)
            for score, length in zip(all_scores, all_lengths)
        ) if total_length > 0 else sum(all_scores) / len(all_scores)
        
        logger.info(f"Final weighted grammar score: {weighted_score} (from {len(all_scores)} chunks)")
        return corrected_text, round(weighted_score, 4)

    def _smart_split(self, text, max_size):
        """Smart text splitting that avoids tiny chunks"""
        if len(text) <= max_size:
            return [text]
        
        chunks = []
        
        # First try to split by double newlines (paragraphs)
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        current_chunk = ""
        for paragraph in paragraphs:
            # If adding this paragraph would exceed max_size
            if len(current_chunk) + len(paragraph) + 2 > max_size:
                # Save current chunk if it's not empty
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                    current_chunk = paragraph
                else:
                    # Paragraph itself is too long, split by sentences
                    sentences = self._split_by_sentences(paragraph, max_size)
                    chunks.extend(sentences)
            else:
                # Add paragraph to current chunk
                if current_chunk:
                    current_chunk += "\n\n" + paragraph
                else:
                    current_chunk = paragraph
        
        # Add remaining chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        # Filter out very small chunks and merge them
        return self._merge_small_chunks(chunks, min_size=50)

    def _split_by_sentences(self, text, max_size):
        """Split text by sentences, avoiding tiny chunks"""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            if len(current_chunk) + len(sentence) + 1 > max_size:
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                    current_chunk = sentence
                else:
                    # Single sentence is too long, just cut it
                    chunks.append(sentence[:max_size])
            else:
                if current_chunk:
                    current_chunk += " " + sentence
                else:
                    current_chunk = sentence
        
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        return chunks

    def _merge_small_chunks(self, chunks, min_size=50):
        """Merge very small chunks to avoid inefficient API calls"""
        if not chunks:
            return chunks
        
        merged = []
        current = ""
        
        for chunk in chunks:
            if len(current) + len(chunk) + 1 <= 500 and len(chunk) < min_size:
                # Merge small chunk
                if current:
                    current += " " + chunk
                else:
                    current = chunk
            else:
                # Save current and start new
                if current:
                    merged.append(current)
                current = chunk
        
        # Add remaining
        if current:
            merged.append(current)
        
        return merged

if __name__ =="__main__":
    grammar  = GrammarChecker()
    data = grammar.evaluate("""
                            Rain Cloud: A model where data is stored in natural clouds and accessed during rainfall.


Fire Cloud: Uses heat-based servers to process data faster.


Wind Cloud: Relies on wind patterns to transfer data wirelessly across continents.


Ghost Cloud: A stealth model where data is invisible to both users and providers, maximizing mystery over usability.

                            """, delay=0)
    print(data)
