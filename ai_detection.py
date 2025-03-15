from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from generated_text_detector.utils.text_detector import GeneratedTextDetector # type: ignore
import uvicorn

app = FastAPI()

# Load detector once at startup
detector = GeneratedTextDetector(
    "SuperAnnotate/ai-detector",
    device="cpu",
    preprocessing=True
)

class TextRequest(BaseModel):
    text: str

@app.post("/detect")
async def detect(request: TextRequest):
    if not request.text:
        raise HTTPException(status_code=400, detail="No text provided")
        
    try:
        result = detector.detect_report(request.text)
        
        # Extract probability from result
        probability = result.get("probability", 0)
        
        return {
            "probability": round(float(probability), 4),
            "original_text_length": len(request.text)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)