# >> Import necessary modules and packages from FastAPI and other libraries
from apis.student import router as student
from apis.superadmin import router as superadmin
from apis.universityadmin import router as universityadmin
from apis.teacher_course import router as teacher_course
from apis.teacher_assigment import router as teacher_assigment
from apis.auth import router as token
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(token)
app.include_router(superadmin)
app.include_router(universityadmin)
app.include_router(teacher_course)
app.include_router(teacher_assigment)
app.include_router(student)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
