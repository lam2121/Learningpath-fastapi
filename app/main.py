from fastapi import FastAPI
from app.api_router import api_router

app = FastAPI(title="TOEIC Learning Path API")

# Bơm "tổng đài" API vào app chính với prefix chung là /api
app.include_router(api_router, prefix="/api")

@app.get("/")
def read_root():
    return {"message": "Welcome to TOEIC Learning Path API!"}