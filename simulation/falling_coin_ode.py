#!/usr/bin/env python3
"""
Falling Coin - FIXED VERSION WITH SEQUENTIAL TRAIL AND THINNER, ROUNDED APPEARANCE
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from scipy.integrate import solve_ivp

C_T = 1.2
C_R = np.pi
A = 1.4
B = 1.0
mu_1 = 0.2
mu_2 = 0.2

def circulation(vx, vy, omega):
    v_mag = np.sqrt(vx**2 + vy**2)
    if v_mag < 1e-10:
        return 2 * C_R * omega / np.pi
    return (2 / np.pi) * (-C_T * vx * vy / v_mag + C_R * omega)

def drag_force(vx, vy):
    v_mag = np.sqrt(vx**2 + vy**2)
    if v_mag < 1e-10:
        return np.array([0.0, 0.0])
    drag_coeff = A - B * (vx**2 - vy**2) / (v_mag**2)
    drag_mag = (1 / np.pi) * drag_coeff * v_mag
    return np.array([drag_mag * vx, drag_mag * vy])

def dissipative_torque(omega):
    return (mu_1 + mu_2 * np.abs(omega)) * omega

def falling_coin_ode(t, state, I_star):
    vx, vy, theta, omega = state
    Gamma = circulation(vx, vy, omega)
    F_drag = drag_force(vx, vy)
    tau_nu = dissipative_torque(omega)
    dvx_dt = ((I_star + 1) * omega * vy - Gamma * vy - np.sin(theta) - F_drag[0]) / I_star
    dvy_dt = (-I_star * omega * vx + Gamma * vx - np.cos(theta) - F_drag[1]) / (I_star + 1)
    moment_of_inertia = 0.25 * (I_star + 0.5)
    domega_dt = (-vx * vy - tau_nu) / moment_of_inertia
    dtheta_dt = omega
    return [dvx_dt, dvy_dt, dtheta_dt, domega_dt]

def simulate_coin(I_star, t_span=(0, 50)):
    # Start with small angle to trigger instability faster
    initial_state = [0.0, -1.0, 0.1, 0.0]
    
    sol = solve_ivp(
        lambda t, state: falling_coin_ode(t, state, I_star),
        t_span,
        initial_state,
        method='RK45',
        dense_output=True,
        rtol=1e-9,
        atol=1e-11
    )
    
    t_eval = np.linspace(t_span[0], t_span[1], 2000)
    solution = sol.sol(t_eval)
    vx, vy, theta, omega = solution
    
    vx_lab = vx * np.cos(theta) - vy * np.sin(theta)
    vy_lab = vx * np.sin(theta) + vy * np.cos(theta)
    
    x = np.cumsum(vx_lab) * (t_eval[1] - t_eval[0])
    y = np.cumsum(vy_lab) * (t_eval[1] - t_eval[0])
    
    return t_eval, solution, x, y

def create_animation():
    print("Simulating fluttering (I* = 1.1)...")
    t1, sol1, x1, y1 = simulate_coin(I_star=1.1)
    
    print("Simulating tumbling (I* = 1.4)...")
    t2, sol2, x2, y2 = simulate_coin(I_star=1.4)
    
    print("Simulating periodic mixture (I* = 1.6)...")
    t3, sol3, x3, y3 = simulate_coin(I_star=1.6)
    
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle('Falling Coin: Fluttering, Tumbling, Periodic Mixture', 
                 fontsize=14, fontweight='bold')
    
    data = [
        (t1, sol1, x1, y1, r"Fluttering ($I^* = 1.1$)"),
        (t2, sol2, x2, y2, r"Tumbling ($I^* = 1.4$)"),
        (t3, sol3, x3, y3, r"Periodic Mixture ($I^* = 1.6$)")
    ]
    
    bounds = []
    for _, _, x, y, _ in data:
        x_min, x_max = x.min(), x.max()
        y_min, y_max = y.min(), y.max()
        x_range = x_max - x_min
        y_range = y_max - y_min
        padding_x = 0.2 * x_range if x_range > 0 else 1.0
        padding_y = 0.2 * y_range if y_range > 0 else 1.0
        bounds.append((
            x_min - padding_x, x_max + padding_x,
            y_min - padding_y, y_max + padding_y
        ))
    
    lines = []
    start_markers = []
    end_markers = []
    
    # Store line objects and pre-calculated data for dynamic trail coins
    all_trail_lines = []
    all_trail_data = []
    
    for idx, (ax, (t, sol, x, y, title), (x_min, x_max, y_min, y_max)) in enumerate(zip(axes, data, bounds)):
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        ax.set_aspect('equal')
        ax.set_title(title, fontsize=12, fontweight='bold')
        ax.set_xlabel('x (dimensionless)', fontsize=10)
        if idx == 0:
            ax.set_ylabel('y (dimensionless)', fontsize=10)
        ax.grid(True, alpha=0.3)
        
        # Trajectory line
        line, = ax.plot([], [], 'b-', alpha=0.6, linewidth=1.5)
        lines.append(line)
        
        # Markers
        start, = ax.plot([], [], 'go', markersize=10, zorder=5)
        end, = ax.plot([], [], 'ro', markersize=10, zorder=5)
        start_markers.append(start)
        end_markers.append(end)
        
        # --- PREPARE DYNAMIC TRAIL COINS ---
        n_coins = 40
        indices = np.linspace(0, len(x)-1, n_coins, dtype=int)
        
        trail_lines_for_ax = []
        trail_data_for_ax = []
        
        print(f"Preparing {n_coins} trail states for {title}")
        for coin_idx in indices:
            # Create the line object but leave it empty for now
            gl, = ax.plot([], [], 'r-', linewidth=1.5, alpha=0.3, zorder=3)
            trail_lines_for_ax.append(gl)
            
            # Pre-calculate coordinates for axial line (thinner)
            theta = sol[2, coin_idx]
            coin_length = 0.8  # slightly shorter for visual appearance
            dx = coin_length * np.cos(theta)
            dy = coin_length * np.sin(theta)
            
            trail_data_for_ax.append({
                'index': coin_idx,
                'x': [x[coin_idx] - dx, x[coin_idx] + dx],
                'y': [y[coin_idx] - dy, y[coin_idx] + dy]
            })
            
        all_trail_lines.append(trail_lines_for_ax)
        all_trail_data.append(trail_data_for_ax)
        
    plt.tight_layout()
    
    n_frames = len(t1)
    frame_skip = max(1, n_frames // 500)
    
    # Initialize objects with empty data
    def init():
        artists = []
        for line in lines:
            line.set_data([], [])
            artists.append(line)
        for start, end in zip(start_markers, end_markers):
            start.set_data([], [])
            end.set_data([], [])
            artists.extend([start, end])
        
        # Initialize trail lines as empty
        for trail_group in all_trail_lines:
            for gl in trail_group:
                gl.set_data([], [])
                artists.append(gl)
                
        return artists
    
    # Animate function
    def animate(frame_idx):
        idx = frame_idx * frame_skip
        if idx >= n_frames:
            idx = n_frames - 1
        
        updated_artists = []
        
        for subplot_idx, (t, sol, x, y, _) in enumerate(data):
            current_idx = min(idx, len(x) - 1)
            
            # Update trajectory
            lines[subplot_idx].set_data(x[:current_idx+1], y[:current_idx+1])
            updated_artists.append(lines[subplot_idx])
            
            # Update markers
            if current_idx > 0:
                start_markers[subplot_idx].set_data([x[0]], [y[0]])
                updated_artists.append(start_markers[subplot_idx])
            
            if current_idx == len(x) - 1:
                end_markers[subplot_idx].set_data([x[-1]], [y[-1]])
                updated_artists.append(end_markers[subplot_idx])
            
            # --- UPDATE TRAIL COINS DYNAMICALLY ---
            trail_lines_for_ax = all_trail_lines[subplot_idx]
            trail_data_for_ax = all_trail_data[subplot_idx]
            
            for gl, gdata in zip(trail_lines_for_ax, trail_data_for_ax):
                # Only reveal the trail coin if the current animation index has passed it
                if current_idx >= gdata['index']:
                    gl.set_data(gdata['x'], gdata['y'])
                else:
                    gl.set_data([], [])
                updated_artists.append(gl)
                
            # --- RENDER CURRENT COIN (THIN & ROUNDED) ---
            x_pos = x[current_idx]
            y_pos = y[current_idx]
            theta = sol[2, current_idx]
            
            # Calculate axial line points
            coin_length = 0.8
            dx = coin_length * np.cos(theta)
            dy = coin_length * np.sin(theta)
            
            p1 = (x_pos - dx, y_pos - dy)
            p2 = (x_pos + dx, y_pos + dy)
            
            # Create a thin line for the body and larger points for rounded ends
            # This combination in ax.plot is efficient for blitting
            current_coin_body, = axes[subplot_idx].plot([p1[0], p2[0]], [p1[1], p2[1]], 'r-', linewidth=2, zorder=10)
            current_coin_ends, = axes[subplot_idx].plot([p1[0], p2[0]], [p1[1], p2[1]], 'ro', markersize=0.8, zorder=10)
            
            updated_artists.extend([current_coin_body, current_coin_ends])
        
        return updated_artists
    
    n_animation_frames = n_frames // frame_skip
    anim = animation.FuncAnimation(
        fig, 
        animate, 
        init_func=init,
        frames=n_animation_frames,
        interval=20,
        blit=True,
        repeat=True
    )
    
    return fig, anim

if __name__ == "__main__":
    print("Creating falling coin animation...")
    fig, anim = create_animation()
    print("\nAnimation complete!")
    
    # Save as MP4
    print("Saving animation as MP4...")
    anim.save('falling_coin_animation.mp4',
              writer='ffmpeg', 
              fps=30, 
              dpi=150,
              bitrate=2000)
    print("Saved to falling_coin_animation.mp4")
    
    plt.show()