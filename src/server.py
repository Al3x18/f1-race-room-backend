import sys
from flask import Flask, jsonify, request
from telemetry import Telemetry
from send_telemetry_file import SendTelemetryFile

server = Flask(__name__)

@server.route('/')
def index():
    return 'Race Room Server!'

@server.route('/status')
def status():
    return jsonify({'status': 'online'})

@server.route('/get-telemetry', methods=['GET'])
def get_telemetry():
    try:
        # Get parameters from request
        year = int(request.args.get('year'))
        track_name = request.args.get('trackName')
        session = request.args.get('session')
        driver_name = request.args.get('driverName')

        send_manager = SendTelemetryFile()

        print(f"Received request with parameters: year={year}, trackName={track_name}, session={session}, driverName={driver_name}")

        telemetry = Telemetry(year=year, track_name=track_name, session=session, driver_name=driver_name)
        file_path = telemetry.get_fl_telemetry()

        response = send_manager.send_file_from_path(file_path=file_path)
        send_manager.delete_file(file_path) # Remove to keep the file on the server

        if response.status_code != 200:
            print(f"Error sending telemetry file: {response.data}")
            return jsonify({'error': 'Error sending telemetry file'}), 500
        
        print("Telemetry file sent successfully")
        return response
    
    except AttributeError as e:
        print(f"AttributeError: {e}")
        return jsonify({'error': 'Data not found. Could not process telemetry data. Please check the provided parameters.'}), 400
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

if __name__ == '__main__':
    port = 5050  # default port
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("Invalid port number. Using default port 5000.")
    
    print(f"Server started on port {port}...")
    server.run(host='0.0.0.0', port=port)