import os
import fastf1 as ff1
from flask import jsonify
import matplotlib
import matplotlib.pyplot as plt
import shutil

matplotlib.use('Agg')  # Non-interactive backend

# Define a custom cache directory
cache_directory = "./custom_cache" 
os.makedirs(cache_directory, exist_ok=True)

ff1.Cache.enable_cache(cache_directory)
ff1.Cache.set_disabled()

class Telemetry:
    def __init__(self, year: int, track_name: str, session: str, driver_name: str):
        self.year = year
        self.track_name = track_name
        self.session = session
        self.driver_name = driver_name

    def load_session_data(self):
        try:
            session = ff1.get_session(self.year, self.track_name, self.session)
            session.load()
            return session
        except Exception as e:
            print(f"Error loading session data: {e}")
            return None
        finally:
            ff1.Cache.clear_cache(cache_dir=cache_directory)
            print("Cache cleared")

    def get_fl_telemetry(self):
        try:
            session = self.load_session_data()
            if session is None:
                return jsonify({"error": "Session data could not be loaded"}), 500

            driver_laps = session.laps.pick_drivers(self.driver_name)
            if driver_laps.empty:
                return jsonify({"error": f"No laps found for driver {self.driver_name}"}), 404

            fastest_lap = driver_laps.pick_fastest()
            telemetry = fastest_lap.get_telemetry()

            return self.build_fastest_lap_plot(telemetry, fastest_lap)
        except Exception as e:
            print(f"Error getting telemetry: {e}")
            return f"Error: Unable to retrieve telemetry - {e}", 500

    def build_fastest_lap_plot(self, telemetry, fastest_lap) -> str:
        try:
            lap_minutes = str(fastest_lap.LapTime).split()[2].split(":")[1].split("0")[1]
            lap_seconds = str(fastest_lap.LapTime).split()[2].split(":")[2][:-3]
            formatted_lap_time = f"{lap_minutes}:{lap_seconds}"

            # Build the plot
            plt.figure(figsize=(12, 8))

            # Speed plot
            plt.subplot(3, 1, 1)
            plt.plot(telemetry['Distance'], telemetry['Speed'], label='Speed (km/h)', color='blue')
            plt.xlabel('Distance (m)')
            plt.ylabel('Speed (km/h)')
            plt.title(f'FASTEST LAP TELEMETRY DATA\n\n{self.driver_name} ({self.session}, {self.track_name}, {self.year})\nLap: {formatted_lap_time}\nPersonal Best: {"Yes" if fastest_lap.IsPersonalBest else "No"}\nCompound: {fastest_lap.Compound}\nTyre Life: {fastest_lap.TyreLife} laps\nFresh Tyre: {"Yes" if fastest_lap.FreshTyre else "No"}\nTeam: {fastest_lap.Team}\n')
            plt.legend()

            # Throttle plot
            plt.subplot(3, 1, 2)
            plt.plot(telemetry['Distance'], telemetry['Throttle'], label='Throttle', color='green')
            plt.xlabel('Distance (m)')
            plt.ylabel('Throttle (%)')
            plt.title('Throttle')
            plt.legend()

            # Brake plot
            plt.subplot(3, 1, 3)
            plt.plot(telemetry['Distance'], telemetry['Brake'] * 100, label='Brake', color='red')
            plt.xlabel('Distance (m)')
            plt.ylabel('Brake (%)')
            plt.title('Brake')
            plt.legend()

            # Save the plot
            os.makedirs("./telemetry_files", exist_ok=True)
            file_path = f"./telemetry_files/{self.driver_name}_{self.session}_{self.track_name}_{self.year}.pdf"
            plt.tight_layout()
            plt.savefig(file_path)
            plt.close()

            return file_path
        except Exception as e:
            print(f"Error generating telemetry plot: {e}")
            return f"Error: Unable to generate plot - {e}", 500