# ChairFactory Parameter Reference

This document provides a comprehensive overview of the parameters controlled by the `ChairFactory` class in Infinigen, which generates procedural chairs with randomized but reproducible variations.

## How Random Seeds Work

The `ChairFactory` uses the `factory_seed` parameter to create reproducible randomness. All random parameters are generated within a `FixedSeed(self.factory_seed)` context, ensuring that the same seed always produces the same chair design.

## Parameter Categories

### 1. Overall Dimensions

| Parameter | Range | Description |
|-----------|-------|-------------|
| `width` | `uniform(0.4, 0.5)` | Overall chair width |
| `size` | `uniform(0.38, 0.45)` | Overall chair depth/length |
| `thickness` | `uniform(0.04, 0.08)` | General thickness for parts |
| `bevel_width` | `thickness * (0.1 if uniform() < 0.4 else 0.5)` | Edge rounding amount |

### 2. Seat Configuration

| Parameter | Range | Description |
|-----------|-------|-------------|
| `seat_back` | `uniform(0.7, 1.0)` if `uniform() < 0.75` else `1.0` | Back edge position |
| `seat_mid` | `uniform(0.7, 0.8)` | Middle seat width |
| `seat_mid_x` | `uniform(seat_back + seat_mid * (1 - seat_back), 1)` | Middle X position |
| `seat_mid_z` | `uniform(0, 0.5)` | Middle seat height curve |
| `seat_front` | `uniform(1.0, 1.2)` | Front edge extension |
| `is_seat_round` | `uniform() < 0.6` | Whether seat has rounded edges (60% chance) |
| `is_seat_subsurf` | `uniform() < 0.5` | Whether to apply subdivision surface (50% chance) |

### 3. Leg Configuration

| Parameter | Range | Description |
|-----------|-------|-------------|
| `leg_thickness` | `uniform(0.04, 0.06)` | Leg thickness |
| `limb_profile` | `uniform(1.5, 2.5)` | Leg curve profile |
| `leg_height` | `uniform(0.45, 0.5)` | Leg length |
| `is_leg_round` | `uniform() < 0.5` | Round vs square legs (50% chance) |
| `leg_type` | Random choice from `["vertical", "straight", "up-curved", "down-curved"]` | Leg style |

### 4. Leg Positioning & Structure

| Parameter | Range | Description |
|-----------|-------|-------------|
| `leg_x_offset` | `width * uniform(0.05, 0.2)` | Leg splay in X direction |
| `leg_y_offset` | `size * uniform(0.05, 0.2, 2)` | Leg splay in Y direction |
| `has_leg_x_bar` | `uniform() < 0.6` | Horizontal support bars (60% chance) |
| `has_leg_y_bar` | `uniform() < 0.6` | Front/back support bars (60% chance) |
| `leg_offset_bar` | `uniform(0.2, 0.4), uniform(0.6, 0.8)` | Bar height range |

### 5. Backrest Configuration

| Parameter | Range | Description |
|-----------|-------|-------------|
| `back_height` | `uniform(0.4, 0.5)` | Backrest height |
| `back_thickness` | `uniform(0.04, 0.05)` | Backrest thickness |
| `back_type` | Weighted choice from: | Backrest style |
| | - `"whole"` (25% chance) | Full backrest |
| | - `"partial"` (25% chance) | Partial backrest |
| | - `"horizontal-bar"` (25% chance) | Horizontal slats |
| | - `"vertical-bar"` (25% chance) | Vertical slats |
| `back_vertical_cuts` | `np.random.randint(1, 4)` | Number of vertical cuts |
| `back_partial_scale` | `uniform(1, 1.4)` | Scale for partial backrest |

### 6. Armrest Configuration

| Parameter | Range | Description |
|-----------|-------|-------------|
| `has_arm` | `uniform() < 0.7` | Whether chair has armrests (70% chance) |
| `arm_thickness` | `uniform(0.04, 0.06)` | Armrest thickness |
| `arm_height` | `arm_thickness * uniform(0.6, 1)` | Armrest height |
| `arm_y` | `uniform(0.8, 1) * size` | Armrest Y position |
| `arm_z` | `uniform(0.3, 0.6) * back_height` | Armrest Z position |
| `arm_mid` | `uniform(-0.03, 0.03), uniform(-0.03, 0.09), uniform(-0.09, 0.03)` | Armrest curve |
| `arm_profile` | `log_uniform(0.1, 3, 2)` | Armrest curve profile |

### 7. Materials & Surface

| Parameter | Range | Description |
|-----------|-------|-------------|
| Limb material | Randomly selected from `material_assignments.furniture_leg` | Leg material type |
| Surface material | Randomly selected from `material_assignments.furniture_hard_surface` | Main surface material |
| Panel material | 30% chance to use same as surface, otherwise random furniture material | Panel material type |
| Wear & tear | Optional scratch and edge wear effects based on probability | Surface aging effects |

## How Different Seeds Create Variety

Each seed generates a completely different combination of these parameters, resulting in:

### Size Variations
- Different overall dimensions (width, size, thickness)
- Varying leg heights and backrest heights
- Different armrest proportions

### Shape Variations
- Round vs square elements (legs, seat edges)
- Curved vs straight leg profiles
- Different seat curvature and backrest shapes

### Structural Variations
- With/without armrests (70% chance)
- Different backrest types (whole, partial, bars)
- Optional support bars between legs
- Various leg splay angles

### Material Variations
- Different wood/metal/fabric materials
- Optional wear and tear effects
- Surface vs panel material differences

### Style Variations
- Modern vs traditional designs
- Minimalist vs ornate structures
- Different leg types (vertical, curved, etc.)

## Example Seed Effects

| Seed | Possible Result |
|------|----------------|
| 42 | Modern chair with round legs, no armrests, horizontal bar backrest |
| 100 | Traditional chair with square legs, armrests, full backrest |
| 200 | Minimalist chair with vertical legs, partial backrest, no support bars |
| 300 | Ornate chair with curved legs, armrests, vertical bar backrest |
| 500 | Simple chair with straight legs, no armrests, whole backrest |

## Usage Example

```python
from infinigen.assets.objects.seating.chairs.chair import ChairFactory

# Generate a chair with seed 42
fac = ChairFactory(factory_seed=42)
chair = fac.spawn_asset(0)

# Generate a different chair with seed 100
fac2 = ChairFactory(factory_seed=100)
chair2 = fac2.spawn_asset(0)
```

## Key Benefits

1. **Reproducibility**: Same seed always produces the same chair
2. **Variety**: Different seeds create unique designs
3. **Realism**: Parameters are based on real furniture proportions
4. **Efficiency**: Procedural generation is faster than manual modeling
5. **Scalability**: Can generate thousands of unique chairs quickly

---

*Generated from Infinigen ChairFactory analysis*

