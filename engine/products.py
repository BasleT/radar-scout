"""Product registry. Units are from ICD 2620002AA Table XVII-I (the extracted text of that table is garbled; the
unit per moment was read from it and cross-checked against Py-ART/xradar naming, so treat as [V-secondary]).
Conversion for every product: value = (N - offset) / scale with the radial's OWN block scale/offset, N>=2 only;
N=0 below threshold, N=1 range folded (Table XVII-I note 21, which names all six moments).

`thresholds` are the display-reduction cut-offs published for the viewer. `rule` says how a gate is kept:
"ge" value >= T, "absge" |value| >= T (radial velocity, either sign), "le" value <= T (correlation
coefficient: nearly all gates have high values, so the viewer lists the lower values, which is what makes the
artifact small enough for a phone; the high values are NOT drawn). These are display choices, not scientific
thresholds for any phenomenon.
"""
PRODUCTS = {
    "REF": dict(label="Reflectivity", unit="dBZ", rule="ge", thresholds=(20, 30, 40, 50)),
    "VEL": dict(label="Radial velocity", unit="m/s", rule="absge", thresholds=(5, 10, 20, 30)),
    "SW": dict(label="Spectrum width", unit="m/s", rule="ge", thresholds=(2, 4, 6, 8)),
    "ZDR": dict(label="Differential reflectivity", unit="dB", rule="ge", thresholds=(0.5, 1, 2, 3)),
    "PHI": dict(label="Differential phase", unit="deg", rule="ge", thresholds=(45, 90, 180, 270)),
    "RHO": dict(label="Correlation coefficient", unit="1", rule="le", thresholds=(0.7, 0.8, 0.9, 0.95)),
}


def keep_mask(product, values, threshold):
    import numpy as np
    v = np.asarray(values, dtype=np.float64)
    rule = PRODUCTS[product]["rule"]
    return (np.abs(v) >= threshold) if rule == "absge" else (v <= threshold) if rule == "le" else (v >= threshold)
