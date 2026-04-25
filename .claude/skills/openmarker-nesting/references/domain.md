# OpenMarker Domain Reference

This file is the authoritative domain knowledge base for the OpenMarker nesting skill.
Load relevant sections when answering questions about specific terms, rules, or algorithm constraints.

---

## Table of contents

1. [Glossary](#glossary)
2. [Fabric type rules](#fabric-type-rules)
3. [Piece orientation rules](#piece-orientation-rules)
4. [Pattern matching rules](#pattern-matching-rules)
5. [Defect and avoid-area rules](#defect-and-avoid-area-rules)
6. [Marker efficiency and yield](#marker-efficiency-and-yield)
7. [Common algorithm constraints](#common-algorithm-constraints)
8. [Common failure causes](#common-failure-causes)
9. [Data model notes](#data-model-notes)
10. [Terminology disambiguation](#terminology-disambiguation)

---

## Glossary

**marker**
A planned layout of all garment pattern pieces on a specific width of fabric, arranged to
minimize waste. A marker defines piece positions, orientations, and the total fabric length
consumed. Markers are produced for specific size mixes and fabric rolls.

**marker layout**
The spatial arrangement of all pieces within a marker. The output of the nesting process.

**nesting**
The computational process of placing garment pieces onto the marker area to maximize fabric
utilization while satisfying all manufacturing constraints. Also called "marker making."
Not equivalent to generic 2D bin-packing — grain, nap, pair logic, and matching constraints
make garment nesting a significantly more constrained problem.

**marker efficiency / fabric utilization**
The ratio of total piece area to total marker area (fabric consumed). Expressed as a percentage.
Higher efficiency = less fabric waste. Industry targets vary by garment type and fabric; typical
production markers run 80–92%. Efficiency below ~75% often signals a constraint violation or
algorithm problem worth investigating.

**yield**
The amount of fabric consumed per unit of output (e.g., meters per garment). Yield and
efficiency are inversely related: higher efficiency = lower yield (less fabric per garment).

**fabric width**
The physical width of the fabric roll, measured selvedge to selvedge.

**usable fabric width**
The effective width available for piece placement, after subtracting selvedge, defects, or
reserved zones. Always use usable width, not gross fabric width, as the placement boundary.
Pieces placed outside the usable width are invalid.

**grainline**
A line printed on each pattern piece indicating the required alignment with the fabric's warp
(lengthwise) threads. Grainline alignment is a hard manufacturing constraint. Deviation from
grainline beyond the allowed tolerance causes the garment to hang incorrectly, stretch
unevenly, or distort after washing.

**grain direction / warp direction**
The lengthwise direction of the fabric, parallel to the selvedge. Grainlines must align with
this direction within the specified tolerance.

**grain deviation tolerance**
The maximum allowed angle between a piece's grainline and the true warp direction. Industry
standard is typically ±1° to ±3° depending on garment type and fabric. This value must come
from the project spec or SME — do not invent a default.

**piece orientation**
The rotation and/or flip state of a pattern piece as placed in the marker.

**rotation allowance**
The set of rotations permitted for a piece. Possible values depend on fabric type and piece
properties. Examples: {0°, 180°} for two-way fabric; {0°} only for one-way; {0°, 90°, 180°, 270°}
if grain can be on either axis (rare in garments). Rotation allowance is a hard constraint when
fabric directionality requires it.

**flip allowance**
Whether a piece may be mirrored (flipped) across an axis for placement. Flipping is prohibited
for one-way and directional fabrics unless the piece is explicitly marked as flip-allowed.
Flipping a piece on napped fabric causes visible nap direction mismatch in the finished garment.

**one-way fabric**
A fabric where all pieces must be placed in the same orientation — the "with-nap" direction.
Reversing a piece (180° rotation or flip) causes visible color or sheen difference in the
finished garment. One-way constraint reduces the effective search space significantly and
typically lowers efficiency compared to two-way layouts.

**two-way fabric**
A fabric with no visible directional difference — pieces may be placed at 0° or 180°, and
sometimes flipped, without visible effect. Two-way markers are easier to optimize.

**directional fabric**
Any fabric that imposes placement direction constraints. Includes one-way, napped, and some
stripe/plaid fabrics. The term "directional" should not be used interchangeably with "one-way";
directional is the broader category.

**nap direction**
The direction in which the fabric's surface texture (nap) lies. Velvet, corduroy, suede-effect
fabrics have a distinct nap. Pieces must be placed with-nap or all against-nap consistently.
Mixing nap directions in one garment produces visible shading differences.

**with-nap / against-nap**
With-nap: pieces placed so the nap runs in the same direction as fabric feed.
Against-nap: pieces placed so the nap runs opposite to feed direction.
Both are valid if used consistently within a garment. The marker spec must declare which mode
applies and enforce it as a hard constraint.

**mirrored pieces**
Pattern pieces that are the mirror image of each other — e.g., a left front and a right front.
They represent separate physical pieces that must both appear in the marker, one as the original
and one as its mirror. Do not confuse with "flip allowance," which is about whether a single
piece may be flipped during placement.

**left/right paired pieces**
A common special case of mirrored pieces. The left piece and right piece of a symmetric
garment section must both be present and correctly oriented. The nesting algorithm must track
pair completeness — a marker missing one half of a pair is invalid.

**symmetric pieces**
Pieces that are identical when mirrored — flipping them produces the same shape. These do not
require pair logic. However, they may still have directional constraints from nap or grain.

**stripe matching**
A constraint requiring that stripe lines on adjacent garment pieces align when the garment is
assembled. Stripe matching requires piece placement to be offset from the fabric's stripe
repeat — this significantly increases effective piece area and reduces marker efficiency.
Stripe matching is a hard visual quality constraint where specified.

**plaid matching / check matching**
Similar to stripe matching but in both warp and weft directions. Plaid matching imposes both
horizontal and vertical repeat offsets, further constraining placement and reducing efficiency
more than stripe matching alone.

**fabric defects**
Physical imperfections in the fabric roll (holes, stains, weave errors, shade variations).
Pieces must not be placed over defects. Defects are entered as known positions before nesting.

**defect zones / avoid areas / no-go areas**
Rectangular or polygonal regions on the fabric where no piece placement is allowed, due to
defects, splices, or reserved areas. These areas reduce the usable layout space and must be
treated as hard placement exclusions by the nesting algorithm.

**lay planning**
The upstream process of deciding how fabric rolls will be spread (number of plies, length)
before cutting. Lay planning outputs inform marker dimensions. Nesting operates within the
bounds set by lay planning.

**bundle**
A stack of cut fabric plies that will be sewn together. Bundle logic may affect which pieces
must be placed adjacently or within the same marker section. Confirm bundle requirements with
the project spec before implementing bundle-aware placement.

**size mix / size ratio**
The quantity of each garment size included in a single marker. A marker may nest pieces for
multiple sizes simultaneously. The algorithm must track required piece counts per size and
ensure all are placed.

---

## Fabric type rules

| Fabric type | Rotation allowed | Flip allowed | Notes |
|---|---|---|---|
| Two-way, no pattern | 0°, 180° | May be allowed | Confirm flip per project spec |
| One-way / napped | 0° only | No | Hard constraint; 180° placement = visible defect |
| Stripe (single axis) | 0°, 180° usually | Per spec | Must also respect stripe repeat offset |
| Plaid / check | Typically 0° only | No | Both axes constrained; very low efficiency expected |
| Symmetric plain | 0°, 90°, 180°, 270° | Usually allowed | Rare in tailored garments |

One-way and napped fabrics: if the algorithm allows any rotation other than 0°, it is a bug,
not an optimization. This is a hard manufacturing constraint, not a preference.

---

## Piece orientation rules

**Grainline alignment check** — for every placed piece:
- Extract grainline vector from piece metadata
- Compute angle between grainline vector and fabric warp axis
- If |angle| > grain_deviation_tolerance → placement is invalid

**Rotation constraint enforcement** — before attempting placement at a given rotation:
- Check the piece's `rotation_allowance` property
- Reject any rotation not in the allowed set
- Do not rely on grain check alone to catch illegal rotations; enforce allowance list explicitly

**Flip constraint enforcement**:
- Check the piece's `flip_allowed` property
- If false and fabric is directional, flip is prohibited regardless of grain check result
- Mirrored-pair pieces have flip handled at pair-definition level, not piece level

---

## Pattern matching rules

**Stripe matching:**
- Each piece has a stripe-match constraint: which seam edges must align to stripe repeat
- Effective placed area of the piece expands to the next repeat boundary — never shrink this
- Two adjacent stripe-matched pieces that share a seam must align at the same repeat position
- Efficiency drop after adding stripe matching is expected; do not treat it as a bug

**Plaid matching:**
- Extends stripe matching to both warp and weft repeat axes
- Each piece's offset is constrained in two dimensions
- Efficiency loss is typically larger than stripe matching alone
- If efficiency drops severely after adding plaid matching, this is likely correct behavior —
  confirm expected efficiency range with SME before investigating algorithm

**Check matching:**
- Common synonym for plaid matching. Use "plaid matching" as the canonical term internally.

---

## Defect and avoid-area rules

- Defect zones are hard exclusion regions: no piece boundary may overlap a defect zone
- Check overlap before accepting any placement candidate
- Defect zones that span the full usable width effectively split the marker into two segments;
  account for this in remaining-space calculations
- A marker that places all pieces while avoiding all defects at lower efficiency is a valid
  output — do not flag this as a failure
- If defect zones consume too much area, the correct outcome is a marker failure with a clear
  message, not a placement that overlaps defects

---

## Marker efficiency and yield

- **Efficiency = (sum of piece areas) / (marker length × usable fabric width)**
- Piece area should use actual piece polygon area, not bounding box area
- Efficiency is computed after all pieces are placed; partial placement does not produce a
  valid efficiency figure
- Expected efficiency ranges vary by garment type — do not hardcode a "good" threshold
  without confirming with the project spec
- Efficiency below ~75% in an unconstrained marker is a signal to investigate; efficiency
  below ~75% in a plaid-matched or heavily constrained marker may be correct

---

## Common algorithm constraints

The nesting algorithm must enforce all of the following simultaneously:

1. All required pieces placed (by size, quantity, and pair completeness)
2. No piece placed outside usable fabric width
3. No piece violates its rotation allowance
4. No piece violates its flip allowance
5. No piece exceeds grain deviation tolerance
6. No piece overlaps another placed piece
7. No piece overlaps a defect zone / avoid area
8. All stripe/plaid-matched pieces respect repeat offsets at constrained seam edges
9. All mirrored pairs include both the original and mirror piece
10. Total marker length does not exceed the available fabric length (if bounded)

Constraints 1–10 are all hard. Violation of any one produces an invalid marker.

---

## Common failure causes

When nesting fails to place all pieces or produces unexpectedly low efficiency:

| Symptom | Likely cause |
|---|---|
| Pieces rejected despite apparent space | Grain deviation check too strict; check tolerance value |
| One-way fabric, many unplaced pieces | 0°-only constraint + poor piece ordering; expected |
| Efficiency drops sharply after config change | New constraint is correct but expensive — confirm expected range |
| Plaid/stripe matching, very low efficiency | Expected — not a bug without confirming with SME |
| Mirror piece missing from output | Pair-completion logic not enforced |
| Defect zone causes failure | Zone spans full width — marker correctly split or failed |
| Valid-looking space shows as occupied | Overlap check using bounding box not polygon — fix to polygon |
| Algorithm times out | Search space too large; likely over-constrained or heuristic issue |
| Marker produced but pieces out of bounds | Usable width not applied correctly (using gross width instead) |

---

## Data model notes

A piece record should carry at minimum:

- `piece_id` — unique identifier
- `geometry` — polygon or outline (not bounding box)
- `grainline_vector` — direction and position of the grainline
- `grain_deviation_tolerance` — max allowed angle in degrees
- `rotation_allowance` — list of permitted rotation values in degrees
- `flip_allowed` — boolean
- `nap_direction` — required if fabric is directional
- `mirror_pair_id` — links the left and right piece of a pair (null if not a pair)
- `is_mirror` — boolean; true if this piece is the mirrored instance in a pair
- `stripe_match_edges` — which edges require stripe alignment (empty if none)
- `plaid_match_edges` — which edges require plaid alignment (empty if none)
- `quantity` — how many of this piece appear in the size mix

A fabric/material record should carry at minimum:

- `gross_width` — physical roll width
- `usable_width` — placement-safe width
- `fabric_type` — one-way / two-way / directional (enum)
- `nap_direction` — if applicable
- `stripe_repeat` — warp repeat value; null if no stripe
- `weft_repeat` — weft repeat value; null if not plaid
- `defect_zones` — list of avoid-area polygons or rectangles

---

## Terminology disambiguation

| User may say | Canonical term | Notes |
|---|---|---|
| "check matching" | plaid matching | Use "plaid matching" internally |
| "opposite pieces" | mirrored pieces / left-right pairs | Clarify which is meant |
| "flip" (as piece action) | flip allowance | A piece property, not an action |
| "direction" (fabric) | directional fabric | Be specific about one-way vs napped vs stripe |
| "efficiency" | marker efficiency | Always define as area ratio, not a qualitative label |
| "yield" | fabric yield (meters/garment) | Inverse of efficiency; clarify direction |
| "nesting" | nesting / marker making | These are synonymous in this project |
| "packing" | nesting | Avoid "packing" — implies generic bin-packing without domain constraints |
| "rotation" (unrestricted) | rotation allowance | Always constrained; clarify allowed values |
