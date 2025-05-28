# >> Import necessary modules and packages from FastAPI and other libraries
from apis.student import router as student
from apis.superadmin import router as superadmin
from apis.universityadmin import router as universityadmin
from apis.teacher_course import router as teacher_course
from apis.teacher_assigment import router as teacher_assigment
from apis.auth import router as token
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psutil
import gc
from fastapi import Request

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add memory monitoring middleware
@app.middleware("http")
async def monitor_memory(request: Request, call_next):
    # Force garbage collection before processing heavy ML tasks
    if "/evaluate" in str(request.url):
        gc.collect()
    
    response = await call_next(request)
    
    # Monitor memory usage
    try:
        memory = psutil.virtual_memory()
        if memory.percent > 85:
            print(f"High memory usage: {memory.percent}%")
            gc.collect()  # Force cleanup
    except:
        pass
    
    return response

# Preload ML models at startup to avoid loading them multiple times
@app.on_event("startup")
async def startup_event():
    print("Preloading ML models for DigitalOcean App Platform...")
    try:
        # Preload models to avoid loading them on each request
        from evaluations.context_score import ContextScorer, TextSimilarity
        from utils.bleurt.bleurt import score as bleurt_score
        
        # Initialize singleton instances
        print("Loading TextSimilarity model...")
        text_sim = TextSimilarity()
        
        print("Loading BLEURT scorer...")
        if ContextScorer._bleurt_scorer is None:
            ContextScorer._bleurt_scorer = bleurt_score.BleurtScorer()
        
        print("ML models preloaded successfully!")
    except Exception as e:
        print(f"Warning: Could not preload ML models: {e}")
        import traceback
        traceback.print_exc()

# Add health check endpoint for DigitalOcean
@app.get("/health")
async def health_check():
    try:
        memory = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.1)
        
        return {
            "status": "healthy",
            "memory_usage": f"{memory.percent:.1f}%",
            "cpu_usage": f"{cpu:.1f}%",
            "available_memory": f"{memory.available / (1024**3):.2f}GB"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

app.include_router(token)
app.include_router(superadmin)
app.include_router(universityadmin)
app.include_router(teacher_course)
app.include_router(teacher_assigment)
app.include_router(student)

if __name__ == "__main__":
    import uvicorn
    
    # For DigitalOcean App Platform - single worker is better for ML models
    uvicorn.run(app, host="0.0.0.0", port=8080, workers=1)
