import matplotlib.pyplot as plt
import numpy as np

# ==========================================
# 1. TVOJE KOMPLETNÍ DATA (6 mincí + 6 podložek)
# ==========================================
nazvy = [
    '1 Kč', '2 Kč', '5 Kč', '10 Kč', '20 Kč', '50 Kč', 
    'Original Washer (11.2g)', 'Washer (Small hole)', 'Washer (Slightly larger)', 
    'Washer (Medium hole)', 'Washer (Large hole)', 'Washer (Largest - Freefall!)'
]

# Všechna Reynoldsova čísla
Re_hodnoty = [
    8291, 9337, 10488, 11760, 11291, 10904,  # Mince
    16290, 11895, 11400, 10133, 9434, 15200  # Podložky
]

# Všechny momenty setrvačnosti
I_star_hodnoty = [
    0.0284, 0.0235, 0.0249, 0.0323, 0.0303, 0.0295,  # Mince
    0.0346, 0.0111, 0.0109, 0.0111, 0.0124, 0.0210   # Podložky
]

# Odlišení: Mince (červené kruhy), tenké podložky (zelené čtverce), anomální tlusté podložky (zlaté hvězdy)
barvy = ['#e63946']*6 + ['gold', '#2a9d8f', '#2a9d8f', '#2a9d8f', '#2a9d8f', 'gold']
tvary = ['o']*6 + ['*', 's', 's', 's', 's', '*']
velikosti = [150]*6 + [450, 150, 150, 150, 150, 450] 

# ==========================================
# 2. NASTAVENÍ GRAFU A ZÓN REŽIMŮ
# Hranice zón jsou schematické (ručně zvolené křivky), ne výsledek výpočtu.
# ==========================================
plt.figure(figsize=(14, 8.5))

x_zone = np.logspace(3, 4.5, 200)

# Křivky
y_flutter_chaos = 0.012 + 0.15 * np.exp(-x_zone / 2000)
y_chaos_tumble = 0.025 + 0.20 * np.exp(-x_zone / 2000)

# Zóny
plt.fill_between(x_zone, 0.001, y_flutter_chaos, color='#4dabf7', alpha=0.15, label='Fluttering (stable)')
plt.fill_between(x_zone, y_flutter_chaos, y_chaos_tumble, color='#ffd43b', alpha=0.25, label='Chaotic transition')
plt.fill_between(x_zone, y_chaos_tumble, 0.1, color='#fa5252', alpha=0.15, label='Tumbling')

# ==========================================
# 3. VYKRESLENÍ BODŮ
# ==========================================
for i in range(len(nazvy)):
    plt.scatter(Re_hodnoty[i], I_star_hodnoty[i], 
                color=barvy[i], marker=tvary[i], 
                s=velikosti[i], edgecolor='black', zorder=5)
    
    # Zarovnání textu (aby se u podložek nepřekrýval)
    if 'Slightly' in nazvy[i]:
        posun_y = -12
    else:
        posun_y = 5
        
    plt.annotate(nazvy[i], (Re_hodnoty[i], I_star_hodnoty[i]), 
                 xytext=(10, posun_y), textcoords='offset points', fontsize=9, fontweight='bold')

plt.xscale('log')
plt.yscale('log')
plt.xlim(5000, 25000)
plt.ylim(0.005, 0.05)

plt.xlabel('Reynolds Number (Re) →', fontsize=13, fontweight='bold')
plt.ylabel('Dimensionless Moment of Inertia (I*) →', fontsize=13, fontweight='bold')
plt.title('Phase Diagram: Coins vs. Washers (schematic regime boundaries)', fontsize=16, fontweight='bold')

plt.grid(True, which="both", linestyle="--", alpha=0.4)
plt.legend(fontsize=11, loc='upper right', framealpha=0.9)
plt.tight_layout()

plt.savefig('phase_diagram.png', dpi=200)
plt.show()