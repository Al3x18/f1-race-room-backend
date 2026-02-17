import os

from fastapi.responses import FileResponse


class SendTelemetryFile:
    @staticmethod
    def send_file_from_path(file_path: str) -> FileResponse:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        return FileResponse(
            path=file_path,
            filename=os.path.basename(file_path),
            media_type="application/pdf",
        )

    @staticmethod
    def delete_file(file_path: str) -> str:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                return "File deleted successfully"
            return "File not found"
        except Exception as exc:
            return f"Error deleting file: {exc}"
