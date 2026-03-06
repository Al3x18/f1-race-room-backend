import fastf1 as ff1
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from src.fastf1_cache import fastf1_cache_guard

matplotlib.use("Agg")


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
            with fastf1_cache_guard():
                loaded_session = ff1.get_session(self.year, self.track_name, self.session)
                loaded_session.load()
            return loaded_session
        except Exception as exc:
            raise TelemetryError(f"Error loading session data: {exc}") from exc

    def get_fl_telemetry(self) -> str:
        session = self.load_session_data()

        driver_laps = session.laps.pick_drivers(self.driver_name)
        if driver_laps.empty:
            raise TelemetryError(f"No laps found for driver {self.driver_name}")

        fastest_lap = driver_laps.pick_fastest()
        telemetry = fastest_lap.get_telemetry()

        return self.build_fastest_lap_plot(session, telemetry, fastest_lap)

    @staticmethod
    def _extract_corner_markers(session, telemetry, distance):
        corner_ticks = []
        corner_labels = []
        try:
            circuit = session.get_circuit_info()
            corners = getattr(circuit, "corners", None)
            if corners is None or corners.empty:
                return [], []

            # Preferred path: FastF1 already gives corner distance.
            if "Distance" in corners.columns:
                for _, corner in corners.iterrows():
                    number = corner.get("Number")
                    corner_distance = corner.get("Distance")
                    if number is None or corner_distance is None:
                        continue
                    corner_ticks.append(float(corner_distance))
                    corner_labels.append(str(int(number)))
            else:
                x = telemetry.get("X")
                y = telemetry.get("Y")
                if x is None or y is None:
                    return [], []
                x_vals = np.asarray(x, dtype=float)
                y_vals = np.asarray(y, dtype=float)
                d_vals = np.asarray(distance, dtype=float)
                finite_mask = np.isfinite(x_vals) & np.isfinite(y_vals) & np.isfinite(d_vals)
                x_vals = x_vals[finite_mask]
                y_vals = y_vals[finite_mask]
                d_vals = d_vals[finite_mask]
                if len(x_vals) == 0:
                    return [], []

                for _, corner in corners.iterrows():
                    cx = corner.get("X")
                    cy = corner.get("Y")
                    number = corner.get("Number")
                    if cx is None or cy is None or number is None:
                        continue
                    distances = (x_vals - float(cx)) ** 2 + (y_vals - float(cy)) ** 2
                    nearest_idx = int(np.argmin(distances))
                    corner_ticks.append(float(d_vals[nearest_idx]))
                    corner_labels.append(str(int(number)))
        except Exception:
            return [], []

        # Remove almost-overlapping markers.
        dedup_ticks = []
        dedup_labels = []
        for tick, label in sorted(zip(corner_ticks, corner_labels), key=lambda item: item[0]):
            if dedup_ticks and abs(tick - dedup_ticks[-1]) < 8:
                continue
            dedup_ticks.append(tick)
            dedup_labels.append(label)
        return dedup_ticks, dedup_labels

    @staticmethod
    def _add_corner_axis(axis, corner_ticks, corner_labels, offset=20):
        if not corner_ticks:
            return
        ax_corner_labels = axis.secondary_xaxis("bottom")
        ax_corner_labels.spines["bottom"].set_position(("outward", offset))
        ax_corner_labels.spines["bottom"].set_color("#2e4358")
        ax_corner_labels.set_xticks(corner_ticks)
        ax_corner_labels.set_xticklabels(corner_labels)
        ax_corner_labels.tick_params(axis="x", colors="#d8e5f6", labelsize=8, pad=1)
        ax_corner_labels.set_xlabel("Corner #", color="#a9bdd2", labelpad=8)

    def get_comparison_telemetry_pdf(self, driver_a: str, driver_b: str) -> str:
        session = self.load_session_data()

        laps_a = session.laps.pick_drivers(driver_a)
        laps_b = session.laps.pick_drivers(driver_b)
        if laps_a.empty:
            raise TelemetryError(f"No laps found for driver {driver_a}")
        if laps_b.empty:
            raise TelemetryError(f"No laps found for driver {driver_b}")

        lap_a = laps_a.pick_fastest()
        lap_b = laps_b.pick_fastest()
        tel_a = lap_a.get_telemetry()
        tel_b = lap_b.get_telemetry()

        return self.build_comparison_plot(
            session=session,
            driver_a=driver_a,
            driver_b=driver_b,
            lap_a=lap_a,
            lap_b=lap_b,
            telemetry_a=tel_a,
            telemetry_b=tel_b,
        )

    @staticmethod
    def _format_lap_time(lap_time) -> str:
        if lap_time is None:
            return "N/A"
        try:
            total_seconds = float(lap_time.total_seconds())
        except Exception:
            return "N/A"
        minutes = int(total_seconds // 60)
        seconds = total_seconds % 60
        return f"{minutes}:{seconds:06.3f}"

    @staticmethod
    def _metric(series, op, default="N/A", decimals=1, suffix=""):
        if series is None:
            return default
        try:
            if len(series) == 0:
                return default
            value = op(series)
            if value is None:
                return default
            return f"{float(value):.{decimals}f}{suffix}"
        except Exception:
            return default

    def build_fastest_lap_plot(self, session, telemetry, fastest_lap) -> str:
        try:
            telemetry = telemetry.copy()
            if "Distance" not in telemetry.columns:
                telemetry["Distance"] = range(len(telemetry))

            distance = telemetry.get("Distance")
            speed = telemetry.get("Speed")
            throttle = telemetry.get("Throttle")
            brake = telemetry.get("Brake")

            if brake is not None:
                brake_pct = brake * 100.0
            else:
                brake_pct = None

            lap_time_label = self._format_lap_time(getattr(fastest_lap, "LapTime", None))
            sector_1 = self._format_lap_time(getattr(fastest_lap, "Sector1Time", None))
            sector_2 = self._format_lap_time(getattr(fastest_lap, "Sector2Time", None))
            sector_3 = self._format_lap_time(getattr(fastest_lap, "Sector3Time", None))

            top_speed = self._metric(speed, lambda s: s.max(), suffix=" km/h")
            avg_speed = self._metric(speed, lambda s: s.mean(), suffix=" km/h")
            full_throttle = self._metric(
                throttle,
                lambda s: (s >= 98).mean() * 100.0,
                suffix="%",
            )
            brake_usage = self._metric(
                brake,
                lambda s: (s > 0).mean() * 100.0,
                suffix="%",
            )

            figure = plt.figure(figsize=(16, 11), facecolor="#0f1720")
            grid = figure.add_gridspec(
                4,
                1,
                height_ratios=[0.85, 2.2, 1.45, 1.45],
                hspace=0.18,
            )

            ax_header = figure.add_subplot(grid[0, 0])
            ax_speed = figure.add_subplot(grid[1, 0])
            ax_throttle = figure.add_subplot(grid[2, 0], sharex=ax_speed)
            ax_brake = figure.add_subplot(grid[3, 0], sharex=ax_speed)

            for axis in (ax_speed, ax_throttle, ax_brake):
                axis.set_facecolor("#131d29")
                axis.tick_params(colors="#b8c6d8")
                for spine in axis.spines.values():
                    spine.set_color("#31475d")

            ax_header.axis("off")
            title = (
                f"{self.driver_name} | {self.track_name} {self.year} {self.session} | "
                f"Fastest Lap {lap_time_label}"
            )
            ax_header.text(
                0.01,
                0.78,
                "F1 Telemetry Report",
                fontsize=21,
                fontweight="bold",
                color="#f5f8ff",
            )
            ax_header.text(
                0.01,
                0.43,
                title,
                fontsize=11.5,
                color="#b8c6d8",
            )

            metadata_line = (
                f"Team: {getattr(fastest_lap, 'Team', 'N/A')}   "
                f"Compound: {getattr(fastest_lap, 'Compound', 'N/A')}   "
                f"Tyre life: {getattr(fastest_lap, 'TyreLife', 'N/A')} laps   "
                f"Personal best: {'Yes' if bool(getattr(fastest_lap, 'IsPersonalBest', False)) else 'No'}"
            )
            ax_header.text(0.01, 0.14, metadata_line, fontsize=10, color="#9bb0c7")

            kpis = [
                ("Top Speed", top_speed),
                ("Avg Speed", avg_speed),
                ("Full Throttle", full_throttle),
                ("Brake Usage", brake_usage),
                ("Sectors", f"S1 {sector_1} | S2 {sector_2} | S3 {sector_3}"),
            ]
            x_positions = [0.56, 0.69, 0.82, 0.56, 0.69]
            y_positions = [0.70, 0.70, 0.70, 0.24, 0.24]
            for idx, (label, value) in enumerate(kpis):
                ax_header.text(
                    x_positions[idx],
                    y_positions[idx],
                    f"{label}\n{value}",
                    ha="left",
                    va="center",
                    fontsize=10,
                    color="#f2f7ff",
                    bbox={
                        "boxstyle": "round,pad=0.42",
                        "fc": "#1c2a3a",
                        "ec": "#36516b",
                        "lw": 1.0,
                    },
                )

            if speed is not None:
                ax_speed.plot(distance, speed, color="#4ea8ff", linewidth=2.2, label="Speed")
            ax_speed.set_title("Speed Profile", color="#eff5ff", fontsize=12, pad=10)
            ax_speed.set_ylabel("km/h", color="#c8d5e5")
            ax_speed.grid(color="#203144", alpha=0.5, linewidth=0.7)
            if speed is not None:
                ax_speed.legend(loc="upper right", frameon=False, labelcolor="#d8e5f6")

            dedup_ticks, dedup_labels = self._extract_corner_markers(
                session=session,
                telemetry=telemetry,
                distance=distance,
            )

            if throttle is not None:
                ax_throttle.plot(
                    distance,
                    throttle,
                    color="#34d399",
                    linewidth=1.8,
                    label="Throttle %",
                )
            ax_throttle.set_title("Throttle", color="#eff5ff", fontsize=12, pad=8)
            ax_throttle.set_ylabel("%", color="#c8d5e5")
            ax_throttle.set_ylim(-2, 104)
            ax_throttle.grid(color="#203144", alpha=0.5, linewidth=0.7)
            if throttle is not None:
                ax_throttle.legend(loc="upper right", frameon=False, labelcolor="#d8e5f6")

            if brake_pct is not None:
                ax_brake.plot(
                    distance,
                    brake_pct,
                    color="#f97316",
                    linewidth=1.7,
                    label="Brake %",
                )
            ax_brake.set_title("Brake", color="#eff5ff", fontsize=12, pad=8)
            ax_brake.set_xlabel("Distance (m)", color="#c8d5e5")
            ax_brake.set_ylabel("%", color="#c8d5e5")
            ax_brake.set_ylim(-2, 104)
            ax_brake.grid(color="#203144", alpha=0.5, linewidth=0.7)
            if brake_pct is not None:
                ax_brake.legend(loc="upper right", frameon=False, labelcolor="#d8e5f6")
            if dedup_ticks:
                self._add_corner_axis(ax_speed, dedup_ticks, dedup_labels, offset=20)
                self._add_corner_axis(ax_throttle, dedup_ticks, dedup_labels, offset=20)
                self._add_corner_axis(ax_brake, dedup_ticks, dedup_labels, offset=22)
                # Speed annotation (km/h) at corner positions for single-driver report.
                if speed is not None:
                    d_vals = np.asarray(distance, dtype=float)
                    s_vals = np.asarray(speed, dtype=float)
                    for tick in dedup_ticks:
                        idx = int(np.argmin(np.abs(d_vals - tick)))
                        if idx < len(s_vals):
                            ax_speed.text(
                                tick,
                                float(s_vals[idx]) + 2.0,
                                f"{int(round(float(s_vals[idx])))} km/h",
                                color="#9ed4ff",
                                fontsize=7,
                                ha="center",
                                va="bottom",
                            )

            os.makedirs("./telemetry_files", exist_ok=True)
            file_path = f"./telemetry_files/{self.driver_name}_{self.session}_{self.track_name}_{self.year}.pdf"
            figure.savefig(file_path, bbox_inches="tight", facecolor=figure.get_facecolor())
            plt.close(figure)

            return file_path
        except Exception as exc:
            raise TelemetryError(f"Error generating telemetry plot: {exc}") from exc

    def build_comparison_plot(
        self,
        session,
        driver_a,
        driver_b,
        lap_a,
        lap_b,
        telemetry_a,
        telemetry_b,
    ) -> str:
        try:
            telemetry_a = telemetry_a.copy()
            telemetry_b = telemetry_b.copy()
            if "Distance" not in telemetry_a.columns:
                telemetry_a["Distance"] = range(len(telemetry_a))
            if "Distance" not in telemetry_b.columns:
                telemetry_b["Distance"] = range(len(telemetry_b))

            distance_a = telemetry_a.get("Distance")
            distance_b = telemetry_b.get("Distance")
            speed_a = telemetry_a.get("Speed")
            speed_b = telemetry_b.get("Speed")
            throttle_a = telemetry_a.get("Throttle")
            throttle_b = telemetry_b.get("Throttle")
            brake_a = telemetry_a.get("Brake")
            brake_b = telemetry_b.get("Brake")
            brake_a_pct = (brake_a * 100.0) if brake_a is not None else None
            brake_b_pct = (brake_b * 100.0) if brake_b is not None else None

            lap_time_a = self._format_lap_time(getattr(lap_a, "LapTime", None))
            lap_time_b = self._format_lap_time(getattr(lap_b, "LapTime", None))

            figure = plt.figure(figsize=(16, 11), facecolor="#0f1720")
            grid = figure.add_gridspec(
                4,
                1,
                height_ratios=[0.85, 2.2, 1.45, 1.45],
                hspace=0.18,
            )

            ax_header = figure.add_subplot(grid[0, 0])
            ax_speed = figure.add_subplot(grid[1, 0])
            ax_throttle = figure.add_subplot(grid[2, 0], sharex=ax_speed)
            ax_brake = figure.add_subplot(grid[3, 0], sharex=ax_speed)

            for axis in (ax_speed, ax_throttle, ax_brake):
                axis.set_facecolor("#131d29")
                axis.tick_params(colors="#b8c6d8")
                for spine in axis.spines.values():
                    spine.set_color("#31475d")

            color_a = "#38bdf8"
            color_b = "#f59e0b"

            ax_header.axis("off")
            ax_header.text(
                0.01,
                0.78,
                "F1 Telemetry Comparison",
                fontsize=21,
                fontweight="bold",
                color="#f5f8ff",
            )
            ax_header.text(
                0.01,
                0.43,
                f"{self.track_name} {self.year} {self.session} | {driver_a} vs {driver_b}",
                fontsize=11.5,
                color="#b8c6d8",
            )
            ax_header.text(
                0.01,
                0.14,
                f"{driver_a}: {lap_time_a}   {driver_b}: {lap_time_b}",
                fontsize=10,
                color="#9bb0c7",
            )

            if speed_a is not None:
                ax_speed.plot(distance_a, speed_a, color=color_a, linewidth=2.0, label=f"{driver_a} speed")
            if speed_b is not None:
                ax_speed.plot(distance_b, speed_b, color=color_b, linewidth=2.0, label=f"{driver_b} speed")
            ax_speed.set_title("Speed Overlay", color="#eff5ff", fontsize=12, pad=10)
            ax_speed.set_ylabel("km/h", color="#c8d5e5")
            ax_speed.grid(color="#203144", alpha=0.5, linewidth=0.7)
            ax_speed.legend(loc="upper right", frameon=False, labelcolor="#d8e5f6")

            if throttle_a is not None:
                ax_throttle.plot(
                    distance_a,
                    throttle_a,
                    color=color_a,
                    linewidth=1.8,
                    label=f"{driver_a} throttle",
                )
            if throttle_b is not None:
                ax_throttle.plot(
                    distance_b,
                    throttle_b,
                    color=color_b,
                    linewidth=1.8,
                    label=f"{driver_b} throttle",
                )
            ax_throttle.set_title("Throttle Overlay", color="#eff5ff", fontsize=12, pad=8)
            ax_throttle.set_ylabel("%", color="#c8d5e5")
            ax_throttle.set_ylim(-2, 104)
            ax_throttle.grid(color="#203144", alpha=0.5, linewidth=0.7)
            ax_throttle.legend(loc="upper right", frameon=False, labelcolor="#d8e5f6")

            if brake_a_pct is not None:
                ax_brake.plot(
                    distance_a,
                    brake_a_pct,
                    color=color_a,
                    linewidth=1.7,
                    label=f"{driver_a} brake",
                )
            if brake_b_pct is not None:
                ax_brake.plot(
                    distance_b,
                    brake_b_pct,
                    color=color_b,
                    linewidth=1.7,
                    label=f"{driver_b} brake",
                )
            ax_brake.set_title("Brake Overlay", color="#eff5ff", fontsize=12, pad=8)
            ax_brake.set_xlabel("Distance (m)", color="#c8d5e5")
            ax_brake.set_ylabel("%", color="#c8d5e5")
            ax_brake.set_ylim(-2, 104)
            ax_brake.grid(color="#203144", alpha=0.5, linewidth=0.7)
            ax_brake.legend(loc="upper right", frameon=False, labelcolor="#d8e5f6")

            corner_ticks, corner_labels = self._extract_corner_markers(
                session=session,
                telemetry=telemetry_a,
                distance=distance_a,
            )
            if corner_ticks:
                self._add_corner_axis(ax_speed, corner_ticks, corner_labels, offset=20)
                self._add_corner_axis(ax_throttle, corner_ticks, corner_labels, offset=20)
                self._add_corner_axis(ax_brake, corner_ticks, corner_labels, offset=22)

                # Speed annotation (km/h) at each corner position for both drivers.
                if speed_a is not None:
                    d_a = np.asarray(distance_a, dtype=float)
                    s_a = np.asarray(speed_a, dtype=float)
                    for tick in corner_ticks:
                        idx = int(np.argmin(np.abs(d_a - tick)))
                        if idx < len(s_a):
                            ax_speed.text(
                                tick,
                                float(s_a[idx]) + 2.0,
                                f"{int(round(float(s_a[idx])))}",
                                color=color_a,
                                fontsize=7,
                                ha="center",
                                va="bottom",
                            )
                if speed_b is not None:
                    d_b = np.asarray(distance_b, dtype=float)
                    s_b = np.asarray(speed_b, dtype=float)
                    for tick in corner_ticks:
                        idx = int(np.argmin(np.abs(d_b - tick)))
                        if idx < len(s_b):
                            ax_speed.text(
                                tick,
                                float(s_b[idx]) - 8.0,
                                f"{int(round(float(s_b[idx])))} km/h",
                                color=color_b,
                                fontsize=7,
                                ha="center",
                                va="top",
                            )

            os.makedirs("./telemetry_files", exist_ok=True)
            file_path = (
                f"./telemetry_files/{driver_a}_{driver_b}_{self.session}_{self.track_name}_{self.year}_comparison.pdf"
            )
            figure.savefig(file_path, bbox_inches="tight", facecolor=figure.get_facecolor())
            plt.close(figure)
            return file_path
        except Exception as exc:
            raise TelemetryError(f"Error generating comparison telemetry plot: {exc}") from exc
