import os
from flask import send_file

class SendTelemetryFile:
   @staticmethod
   def send_file_from_path(file_path):
        """ Given the file path, this function will send the file with flask as an attachment.  """
        try:
            print(f"Attempting to send file from path: {file_path}")
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            return send_file(file_path, as_attachment=True, download_name=os.path.basename(file_path), mimetype='application/pdf')
        except FileNotFoundError as e:
            print(f"File not found: {e}")
            return f"Error: File not found - {e}", 404
        except Exception as e:
            print(f"Error sending file: {e}")
            return f"Error: Unable to send file - {e}", 500
        
   @staticmethod
   def delete_file(file_path):
        """Deletes the file from the filesystem."""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                return "File deleted successfully"
            else:
                return "File not found"
        except Exception as e:
            return f"Error deleting file: {e}"