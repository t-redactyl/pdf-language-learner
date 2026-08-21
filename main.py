"""Development entry point for the PDF Language Learner."""

import uvicorn


if __name__ == "__main__":
    uvicorn.run("pdf_language_learner.app:app", host="127.0.0.1", port=8000, reload=True)
