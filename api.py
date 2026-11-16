import io
import zipfile
from fastapi.responses import StreamingResponse
from pathlib import Path
import shutil
import subprocess
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException
from starlette.concurrency import run_in_threadpool
from conversion_service import convert_sas_code

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


app = FastAPI(
    title="SAS to Java AI Converter API",
    description="Convert SAS programs into Java 21 using GitHub Copilot CLI.",
    version="1.0.0"
)

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

app.mount(
    "/static",
    StaticFiles(directory=FRONTEND_DIR),
    name="static"
)

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "copilot_cli": bool(
            shutil.which("copilot.cmd") or shutil.which("copilot")
        )
    }


@app.post("/convert")
async def convert(file: UploadFile = File(...)):

    # Validate filename
    filename = Path(file.filename or "").name

    if not filename or Path(filename).suffix.lower() != ".sas":
        raise HTTPException(
            status_code=400,
            detail="Only .sas files are supported."
        )

    try:
        # Read uploaded SAS file
        file_content = await file.read(MAX_FILE_SIZE + 1)

        if len(file_content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail="File size exceeds the 5 MB limit."
            )

        if not file_content:
            raise HTTPException(
                status_code=400,
                detail="Uploaded SAS file is empty."
            )

        try:
            sas_code = file_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400,
                detail="Invalid file encoding. Please upload a UTF-8 SAS file."
            )

        # Run the shared conversion engine outside the async event loop
        class_name, java_code = await run_in_threadpool(
            convert_sas_code,
            sas_code,
            filename
        )

        if not java_code.strip():
            raise HTTPException(
                status_code=500,
                detail="Java conversion returned empty output."
            )

        return {
            "status": "success",
            "message": "SAS to Java conversion completed successfully.",
            "source_filename": filename,
            "java_filename": f"{class_name}.java",
            "java_code": java_code
        }

    except HTTPException:
        raise

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="Conversion timed out after 600 seconds."
        )

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Conversion failed. Check the API server terminal for details."
        )

    finally:
        await file.close()


@app.post("/convert-multiple")
async def convert_multiple(
    files: List[UploadFile] = File(...)
):

    MAX_FILES = 20
    MAX_FILE_SIZE = 5 * 1024 * 1024

    if not files:
        raise HTTPException(
            status_code=400,
            detail="Please upload at least one SAS file."
        )

    if len(files) > MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_FILES} SAS files allowed per request."
        )

    zip_buffer = io.BytesIO()
    report = []
    successful = 0
    failed = 0
    generated_names = set()

    try:
        with zipfile.ZipFile(
            zip_buffer,
            mode="w",
            compression=zipfile.ZIP_DEFLATED
        ) as zip_file:

            for file in files:

                try:
                    filename = (
                        (file.filename or "")
                        .replace("\\", "/")
                        .rsplit("/", 1)[-1]
                    )

                    if (
                        not filename
                        or Path(filename).suffix.lower() != ".sas"
                    ):
                        failed += 1
                        report.append(
                            f"FAILED: Invalid SAS filename: {filename}"
                        )
                        continue

                    file_content = await file.read(
                        MAX_FILE_SIZE + 1
                    )

                    if len(file_content) > MAX_FILE_SIZE:
                        failed += 1
                        report.append(
                            f"FAILED: {filename} exceeds 5 MB."
                        )
                        continue

                    if not file_content:
                        failed += 1
                        report.append(
                            f"FAILED: Empty file: {filename}"
                        )
                        continue

                    try:
                        sas_code = file_content.decode("utf-8-sig")
                    except UnicodeDecodeError:
                        failed += 1
                        report.append(
                            f"FAILED: Invalid UTF-8 encoding: {filename}"
                        )
                        continue

                    # Call the shared conversion engine
                    class_name, java_code = await run_in_threadpool(
                        convert_sas_code,
                        sas_code,
                        filename
                    )

                    java_filename = f"{class_name}.java"

                    # Prevent duplicate filenames inside the ZIP
                    if java_filename.lower() in generated_names:
                        failed += 1
                        report.append(
                            f"FAILED: Duplicate Java filename: {java_filename}"
                        )
                        continue

                    if not java_code.strip():
                        failed += 1
                        report.append(
                            f"FAILED: Empty Java output: {filename}"
                        )
                        continue

                    generated_names.add(java_filename.lower())

                    zip_file.writestr(
                        java_filename,
                        java_code + "\n"
                    )

                    successful += 1

                    report.append(
                        f"SUCCESS: {filename} -> {java_filename}"
                    )

                except subprocess.TimeoutExpired:
                    failed += 1
                    report.append(
                        f"FAILED: Conversion timeout: {file.filename}"
                    )

                except Exception as error:
                    failed += 1
                    report.append(
                        f"FAILED: {file.filename}: {error}"
                    )

                finally:
                    await file.close()

            # Add conversion summary
            summary = (
                f"Total files: {len(files)}\n"
                f"Successful: {successful}\n"
                f"Failed: {failed}\n\n"
                + "\n".join(report)
            )

            zip_file.writestr(
                "conversion_report.txt",
                summary
            )

        if successful == 0:
            raise HTTPException(
                status_code=422,
                detail="No files were converted successfully."
            )

        zip_buffer.seek(0)

        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition":
                    'attachment; filename="SAS_to_Java_Results.zip"'
            }
        )

    except HTTPException:
        raise

    finally:
        for file in files:
            if not file.file.closed:
                await file.close()
