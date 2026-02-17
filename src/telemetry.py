import os

import fastf1 as ff1
import matplotlib
import matplotlib.pyplot as plt

matplotlib.use("Agg")

cache_directory = "./custom_cache"
os.makedirs(cache_directory, exist_ok=True)

ff1.Cache.enable_cache(cache_directory)
ff1.Cache.set_disabled()


class TelemetryError(RuntimeError):
    pass


class Telemetry:
    def __init__(self, year: int, track_name: str, session: str, driver_name: str):
        self.year = year
        self.track_name = track_name
        self.session = session
        self.driver_name = driver_name

    def load_session_data(self):
        try:
            loaded_session = ff1.get_session(self.year, self.track_name, self.session)
            loaded_session.load()
            return loaded_session
        except Exception as exc:
            raise TelemetryError(f"Error loading session data: {exc}") from exc
        finally:
            ff1.Cache.clear_cache(cache_dir=cache_directory)

    def get_fl_telemetry(self) -> str:
        session = self.load_session_data()

        driver_laps = session.laps.pick_drivers(self.driver_name)
        if driver_laps.empty:
            raise TelemetryError(f"No laps found for driver {self.driver_name}")

        fastest_lap = driver_laps.pick_fastest()
        telemetry = fastest_lap.get_telemetry()

        return self.build_fastest_lap_plot(telemetry, fastest_lap)

    def build_fastest_lap_plot(self, telemetry, fastest_lap) -> str:
        try:
            lap_seconds_total = float(fastest_lap.LapTime.total_seconds())
            lap_minutes = int(lap_seconds_total // 60)
            lap_seconds = lap_seconds_total % 60
            formatted_lap_time = f"{lap_minutes}:{lap_seconds:06.3f}"

            plt.figure(figsize=(12, 8))

            plt.subplot(3, 1, 1)
            plt.plot(telemetry["Distance"], telemetry["Speed"], label="Speed (km/h)", color="blue")
            plt.xlabel("Distance (m)")
            plt.ylabel("Speed (km/h)")
            plt.title(
                "FASTEST LAP TELEMETRY DATA\n\n"
                f"{self.driver_name} ({self.session}, {self.track_name}, {self.year})\n"
                f"Lap: {formatted_lap_time}\n"
                f"Personal Best: {'Yes' if fastest_lap.IsPersonalBest else 'No'}\n"
                f"Compound: {fastest_lap.Compound}\n"
                f"Tyre Life: {fastest_lap.TyreLife} laps\n"
                f"Fresh Tyre: {'Yes' if fastest_lap.FreshTyre else 'No'}\n"
                f"Team: {fastest_lap.Team}\n"
            )
            plt.legend()

            plt.subplot(3, 1, 2)
            plt.plot(telemetry["Distance"], telemetry["Throttle"], label="Throttle", color="green")
            plt.xlabel("Distance (m)")
            plt.ylabel("Throttle (%)")
            plt.title("Throttle")
            plt.legend()

            plt.subplot(3, 1, 3)
            plt.plot(telemetry["Distance"], telemetry["Brake"] * 100, label="Brake", color="red")
            plt.xlabel("Distance (m)")
            plt.ylabel("Brake (%)")
            plt.title("Brake")
            plt.legend()

            os.makedirs("./telemetry_files", exist_ok=True)
            file_path = f"./telemetry_files/{self.driver_name}_{self.session}_{self.track_name}_{self.year}.pdf"
            plt.tight_layout()
            plt.savefig(file_path)
            plt.close()

            return file_path
        except Exception as exc:
            raise TelemetryError(f"Error generating telemetry plot: {exc}") from exc
