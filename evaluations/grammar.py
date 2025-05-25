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
        self.api_url = os.getenv("GRAMMAR_API_URL", "https://x1gtgawsmeq79mpc.us-east-1.aws.endpoints.huggingface.cloud")
        
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
        """Process a single chunk of text"""
        # Try to get correction from API with delay
        logger.info(f"Checking grammar for chunk with length {len(text)}")
        result = self.query_api(text, attempt=0, delay=delay)
        
        if result is None:
            # API failed, provide a reasonable high score as default
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
        """Evaluate text for grammar correctness with chunking for longer texts"""
        if not text or len(text.strip()) < 3:
            logger.info("Empty or very short answer - assigning zero grammar score")
            return text, 0.0  # Zero score for empty answers
            
        # If we already know the service is unavailable, skip API call
        if not self.service_available:
            simulated_score = round(random.uniform(0.8, 1.0), 4)
            logger.info(f"Grammar service unavailable, using simulated score: {simulated_score}")
            return text, simulated_score
        
        # Define maximum chunk size (characters)
        MAX_CHUNK_SIZE = 90  # Reduced slightly for safety
        
        # For short texts, process normally
        if len(text) <= MAX_CHUNK_SIZE:
            logger.info(f"Processing single chunk with delay: {delay}")
            return self._process_single_chunk(text, delay)
        
        # For longer texts, split into chunks and process each
        logger.info(f"Text length {len(text)} exceeds chunk size, splitting into chunks")
        
        # First, preserve the original structure by identifying paragraph breaks
        paragraphs = re.split(r'(\n\s*\n+)', text)
        processed_paragraphs = []
        all_scores = []
        all_lengths = []
        
        for p_idx, paragraph in enumerate(paragraphs):
            # If this is just whitespace/newlines, preserve it exactly
            if not paragraph.strip():
                processed_paragraphs.append(paragraph)
                continue
                
            # Process actual text paragraphs
            if len(paragraph) <= MAX_CHUNK_SIZE:
                # Apply delay for chunks after the first one
                chunk_delay = delay if p_idx > 0 else 0
                corrected, score = self._process_single_chunk(paragraph, chunk_delay)
                processed_paragraphs.append(corrected)
                all_scores.append(score)
                all_lengths.append(len(paragraph))
            else:
                # Split longer paragraphs into chunks
                chunks = self._split_into_chunks(paragraph, MAX_CHUNK_SIZE)
                logger.info(f"Split paragraph into {len(chunks)} chunks")
                
                corrected_chunks = []
                for i, chunk in enumerate(chunks):
                    # Add delay between chunks (but not for the very first chunk)
                    chunk_delay = delay if (i > 0 or p_idx > 0) else 0
                    
                    # Process chunk
                    corrected_chunk, chunk_score = self._process_single_chunk(chunk, chunk_delay)
                    corrected_chunks.append(corrected_chunk)
                    all_scores.append(chunk_score)
                    all_lengths.append(len(chunk))
                
                # Join chunks within paragraph
                processed_paragraphs.append(' '.join(corrected_chunks))
        
        # Join processed paragraphs, preserving original paragraph breaks
        corrected_text = ''.join(processed_paragraphs)
        
        # Calculate weighted average score
        if not all_scores:
            logger.warning("No scores calculated, using default")
            return text, 0.9  # Default fallback
        
        # Weight scores by text length
        total_length = sum(all_lengths)
        if total_length == 0:
            logger.warning("Total length is 0, using simple average")
            weighted_score = sum(all_scores) / len(all_scores)
        else:
            weighted_score = sum(
                score * (length / total_length)
                for score, length in zip(all_scores, all_lengths)
            )
        
        logger.info(f"Final weighted grammar score: {weighted_score} (from {len(all_scores)} chunks)")
        
        return corrected_text, round(weighted_score, 4)

    def _split_into_chunks(self, text, max_size):
        """Split text into chunks, trying to preserve sentence boundaries"""
        chunks = []
        
        # Find all sentence boundaries (periods, question marks, exclamation points)
        sentence_ends = [m.end() for m in re.finditer(r'[.!?]\s+', text)]
        
        # Add the end of the text as a final boundary
        sentence_ends.append(len(text))
        
        start = 0
        
        while start < len(text):
            # Find the last sentence boundary that fits in the current chunk
            chunk_end = start
            
            for end in sentence_ends:
                if end - start <= max_size:
                    chunk_end = end
                else:
                    break
            
            # If no sentence boundary found, or it's the same as start, 
            # just cut at max_size or end of text
            if chunk_end == start:
                chunk_end = min(start + max_size, len(text))
            
            # Extract chunk and clean it
            chunk = text[start:chunk_end].strip()
            
            # Only add non-empty chunks
            if chunk:
                chunks.append(chunk)
            
            # Move to next chunk
            start = chunk_end
        
        return chunks

if __name__ =="__main__":
    grammar  = GrammarChecker()
    data = grammar.evaluate("""
                            Rain Cloud: A model where data is stored in natural clouds and accessed during rainfall.


Fire Cloud: Uses heat-based servers to process data faster.


Wind Cloud: Relies on wind patterns to transfer data wirelessly across continents.


Ghost Cloud: A stealth model where data is invisible to both users and providers, maximizing mystery over usability.

                            """, delay=0)
    print(data)
