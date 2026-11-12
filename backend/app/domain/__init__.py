"""
Business logic, framework-free.

Route modules parse the request, call in here, and shape the response; the
rules themselves live here so they can be read — and eventually tested —
without an HTTP client or a live database.

ONE EXCEPTION, AND IT IS SMALLER THAN IT WAS

`onboarding/verification/document_processing.py` imports FastAPI's
`UploadFile` for the annotation on its `uploaded_file` parameter. That is a
signature coupling, not a logic one — nothing in this package raises
`HTTPException` or touches a Request — but it is real, and this docstring
used to claim otherwise.

Before B5 the exception was the whole 2,261-line verification.py. Splitting it
confined the import to the one module that needs it: `latest_document.py` and
`response_handling.py` are now genuinely FastAPI-free.

Removing the last of it means changing `process_uploaded_document`'s signature
to take bytes and a filename rather than an `UploadFile`, which is a change to
a function with two callers, not a move. It has not been done.

Verify with:
    grep -rn "fastapi" backend/app/domain/
"""
