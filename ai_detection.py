from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from generated_text_detector.utils.text_detector import GeneratedTextDetector # type: ignore
import uvicorn
import traceback

app = FastAPI()

# Load detector once at startup
try:
    print("Loading AI detection model...")
    detector = GeneratedTextDetector(
        "samadpls/ai-detector",
        device="cpu",
        preprocessing=True
    )
    print("AI detection model loaded successfully")
except Exception as e:
    print(f"ERROR LOADING DETECTOR: {str(e)}")
    traceback.print_exc()
    detector = None

class TextRequest(BaseModel):
    text: str

@app.post("/detect")
async def detect(request: TextRequest):
    if detector is None:
        raise HTTPException(status_code=500, detail="AI detector model not loaded")
        
    if not request.text:
        raise HTTPException(status_code=400, detail="No text provided")
        
    try:
        result = detector.detect_report(request.text)
        
        # Extract probability from result
        probability = result.get("generated_score", 0)
        
        return {
            "probability": round(float(probability), 4),
            "original_text_length": len(request.text)
        }
        
    except Exception as e:
        print(f"Error in detect endpoint: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    if detector is None:
        return {"status": "not ready", "detail": "Model not loaded.."}
    return {"status": "healthy..", "model_loaded": True}

@app.get("/")
async def root():
    return {"message": "AI Detection API is running"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)