from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api_router import api_router
from app.feature.career.career_router import router as career_router
app = FastAPI(title="TOEIC Learning Path API")

# Cho phép frontend (Vite dev server) gọi API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bơm "tổng đài" API vào app chính với prefix chung là /api
app.include_router(api_router, prefix="/api")
app.include_router(career_router, prefix="/career")
@app.get("/")
def read_root():
    return {"message": "Welcome to TOEIC Learning Path API!"}