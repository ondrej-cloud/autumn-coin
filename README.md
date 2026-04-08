# Autumn Coin: 3D tracking of coins falling through water

<p align="center">
  <img src="media/coin_drop_two_cameras.gif" alt="A 10 CZK coin falling through water, filmed from the front and from the side" width="480">
</p>

Drop a coin into water and it almost never falls straight down. It glides sideways, wobbles, flips over and
lands somewhere different every time. This repository holds the experiment and the analysis pipeline that
measure this motion in 3D. The project was a solution to problem 12 of the
**Czech Young Physicists' Tournament (TMF)**, the national round of the IYPT.

> **12. Autumn coin**
> The motion of a coin falling to the bottom of a tank filled with liquid can be remarkably similar to the
> fluttering and tumbling of a falling autumn leaf. Investigate how the motion of the coin depends on relevant
> parameters.

- **143 tracked drops**: 6 Czech coins (1, 2, 5, 10, 20 and 50 CZK) and washers with different central holes
- **Stereo reconstruction** from two phones filming the tank from perpendicular directions
- **Semi-automatic computer-vision tracker** (OpenCV): motion detection, frame differencing, then a manual review and correction editor
- **Statistics over repeated drops**: mean 3D trajectory, ±1σ spread, landing scatter and an energy budget
- **Numerical model** of a falling plate (a quasi-steady ODE model) that reproduces fluttering and tumbling

## Experiment

An electromagnet releases the coin at the water surface, so every drop starts from the same position and
orientation. The water tank is 38 × 32 × 38 cm. Two iPhones (15 Pro and 11) record each drop simultaneously:

| Camera 1 (front) | Camera 2 (side) |
| --- | --- |
| horizontal drift **X** and depth **Y** | horizontal drift **Z** and depth **Y** |

| Coin | Mass | Diameter | Drops |
| --- | --- | --- | --- |
| 1 CZK | 3.6 g | 20.0 mm | 15 |
| 2 CZK | 3.7 g | 21.5 mm | 19 |
| 5 CZK | 4.8 g | 23.0 mm | 18 |
| 10 CZK | 7.62 g | 24.5 mm | 18 |
| 20 CZK | 8.42 g | 26.0 mm | 17 |
| 50 CZK | 9.7 g | 27.5 mm | 16 |

There were also 20 drops of each of two washers, one with a small and one with a large central hole. The motion
is close to chaotic, so a single trajectory says little and the analysis works on the whole ensemble.

## Pipeline

```mermaid
flowchart LR
    A[Raw videos<br/>2 cameras × N drops] --> B[trim_videos.py<br/>cut to release moment]
    B --> C[calibrate.py<br/>pixels → metres]
    C --> D[track_coin.py<br/>auto-track]
    D --> E{review}
    E -- OK --> F[(tracking_cache.json)]
    E -- fix points --> G[manual editor] --> F
    F --> H[3D reconstruction<br/>+ statistics]
    H --> I[plots + CSV]
```

1. **Trimming** (`tracking/trim_videos.py`): step through each recording frame by frame and cut it at the release.
   Uses `ffmpeg` for a lossless cut and falls back to OpenCV if `ffmpeg` is missing.
2. **Calibration** (`tracking/calibrate.py`): click the inner top and bottom edge of the tank in both cameras.
   The script reads phone rotation metadata (`ffprobe`), so portrait videos are handled correctly.
3. **Tracking** (`tracking/track_coin.py`):
   - *Lock-on*: wait for motion in a narrow band just below the surface, under the electromagnet. Waves at the
     surface never trigger the lock this way.
   - *Follow*: frame differencing inside a local search window that moves with the coin. A max-jump limit and
     a "must keep sinking" rule reject reflections and splashes.
   - *Review*: replay the detected path over the video, then accept it, fix individual points in the editor or
     re-click the whole drop by hand.
   - Every accepted track is cached, so the analysis can be re-run without touching the videos.
4. **3D reconstruction and statistics**: the two views are time-synchronised by detecting the onset of the steady
   fall in each camera and interpolated onto a common time axis. Velocities come from a Savitzky–Golay filter.
   The script then averages all drops of one object into a mean trajectory with ±1σ bands, plots the landing
   scatter and computes the potential, kinetic and dissipated energy.

## Results

<table>
  <tr>
    <td><img src="results/coin_10czk/PRUMER_3D_10kc1.png" alt="3D trajectories of 18 drops of a 10 CZK coin"></td>
    <td><img src="results/coin_10czk/TRACKING_vsechny_XY_10kc1.png" alt="All X–Y trajectories of the 10 CZK coin"></td>
  </tr>
  <tr>
    <td align="center"><em>18 drops of a 10 CZK coin in 3D, with the mean trajectory and ±1σ crosses</em></td>
    <td align="center"><em>The same drops seen by the front camera</em></td>
  </tr>
</table>

<p align="center">
  <img src="results/coin_10czk/TRACKING_dopadova_ruzice_10kc1.png" alt="Landing positions of the 10 CZK coin" width="420">
</p>

Each object has a full set of plots and a CSV with the mean trajectory and individual landing points in
[`results/`](results/).

### Coins vs. washers

<p align="center">
  <img src="results/phase_diagram/phase_diagram.png" alt="Phase diagram of Reynolds number vs dimensionless moment of inertia" width="760">
</p>

The falling regime of a thin disk is governed mainly by the Reynolds number *Re* and the dimensionless moment of
inertia *I\**. Coins sit in the tumbling and chaotic part of the diagram. Cutting a hole in the middle (washers)
pushes *I\** down into the fluttering regime. The shaded regime boundaries are schematic.

## Simulation

<p align="center">
  <img src="media/falling_coin_simulation.gif" alt="Simulated fluttering, tumbling and mixed motion of a falling plate" width="900">
</p>

`simulation/falling_coin_ode.py` integrates a 2D quasi-steady model of a plate falling through a fluid. The model
includes circulation-based lift, drag that depends on the angle of attack and a dissipative torque (after
Andersen, Pesavento & Wang, *J. Fluid Mech.* 2005). Changing the moment of inertia switches the motion between
fluttering, tumbling and a periodic mixture of the two.

## Repository structure

```
tracking/
  track_coin.py         main tracker: auto-tracking, review/editor, 3D reconstruction, plots
  calibrate.py          pixel → metre calibration from the tank height
  trim_videos.py        cut recordings to the moment of release
  measure_velocity.py   click two frames, get the terminal velocity
simulation/
  falling_coin_ode.py   quasi-steady falling-plate model + animation
analysis/
  phase_diagram.py      Re vs I* diagram for coins and washers
  angular_velocity.py   angular velocity from two tracked points on the coin rim
data/
  <object>/tracking_cache.json   tracked pixel positions for every drop and camera
  sample_videos/                 two example drops (both cameras) to try the tracker on
results/
  <object>/             plots + CSV for every object
media/                  animations used in this README
```

## Running it

```bash
pip install -r requirements.txt

# Re-create all plots for one object from the tracked data (no videos needed)
python tracking/track_coin.py data/coin_10czk

# Try the interactive tracker on the sample videos (OpenCV windows + terminal prompts)
python tracking/track_coin.py data/sample_videos

# Run the falling-plate simulation (saving the MP4 needs ffmpeg)
python simulation/falling_coin_ode.py
```

Results go to `results/<dataset name>/` by default. Use `-o <folder>` to change that.

### Data format

`tracking_cache.json` maps `<drop>_cam1` / `<drop>_cam2` to a pair of lists `[x_px, y_px]` with one value per
video frame. `x` is measured from the centre of the frame, `y` from the top, and `null` means the coin was not
visible in that frame. The full set of raw recordings (409 videos, ~1.5 GB) is not part of the repository.
Recordings of washers with medium-sized holes were also made but not tracked.

## Team

Team **Olomoucké srnky**, Gymnázium Olomouc-Hejčín: Vojtěch Přibyl, Michael Ambros and Ondřej Novotný.
The tracking and analysis code in this repository was written by Ondřej Novotný.

Thanks to Marek Fürst (MFF UK), the consultant for this problem, for his introductory lecture on it.

## References

- A. Andersen, U. Pesavento, Z. J. Wang, *Analysis of transitions between fluttering, tumbling and steady descent of
  falling cards*, J. Fluid Mech. **541** (2005).
- U. Pesavento, *Unsteady aerodynamics of falling plates*, PhD thesis, Cornell University (2006).
- N. M. Kamaruddin, *Dynamics and performance of flying discs*, PhD thesis, University of Manchester (2011).
- M. Pazout, *Falling leaves simulation*, Master's thesis, CTU in Prague (2022).

## License

[MIT](LICENSE) © Ondřej Novotný
