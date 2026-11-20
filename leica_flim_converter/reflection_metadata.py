"""Metadata and reproducible seeds for synthetic reflection samples."""

import hashlib
import json
import math

import numpy as np

MODE_LABELS = {
    "nan": "Assign to NaNs",
    "interpolate": "Interpolate values (smooth)",
    "simulate": "Simulate photon counts from interpolation",
}
REPAIR_MODES = ("interpolate", "simulate")
SHARED_MODEL = "whole-image log-linear endpoint bridge"


def processing_description(bounds, mode, seed=0):
    """Describe replaced native samples as missing or synthetic."""
    synthetic = mode in REPAIR_MODES
    return {
        "mode": mode,
        "appliedMode": mode,
        "modeLabel": MODE_LABELS.get(mode, "Exclude reflection events"),
        "interpolationModel": SHARED_MODEL if synthetic else None,
        "usesAllImagePixels": synthetic,
        "spatialWeighting": (
            "Each pixel's fraction of counts outside the native interval"
            if synthetic
            else None
        ),
        "replacementKind": {
            "nan": "missing samples",
            "interpolate": "synthetic expected counts",
            "simulate": "synthetic Poisson photon counts",
        }.get(mode, "excluded events"),
        "replacementValuesAreMeasuredPhotons": False,
        "syntheticNativeInterval": {
            "firstBin": math.ceil(bounds[0]),
            "lastBin": math.floor(bounds[1]),
            "scope": "all spatial pixels",
        }
        if synthetic
        else None,
        "baseSeed": str(seed) if mode == "simulate" else None,
        "randomSeed": None,
        "randomGenerator": "numpy.random.PCG64"
        if mode == "simulate"
        else None,
        "numpyVersion": np.__version__ if mode == "simulate" else None,
        "simulationAlgorithmVersion": 1 if mode == "simulate" else None,
        "samplingDistribution": (
            "Independent Poisson draws from each pixel/bin expected count"
            if mode == "simulate"
            else None
        ),
        "sampleOrder": "native bin, then C-order spatial pixels"
        if mode == "simulate"
        else None,
    }


def simulation_context(cube, bounds, seed):
    """Seed draws independently of panel order and output binning."""
    context = {
        "algorithm": "loglinear-poisson-v1",
        "baseSeed": str(seed),
        "datasetKey": cube.source_dataset_key or "",
        # Single-plane overviews and explicit plane zero share a seed.
        "planeSeedIndex": cube.linear_plane or 0,
        "eventFlagMask": cube.event_flag_mask,
        "boundsNative": list(map(float, bounds)),
        "spatialShape": list(cube.counts.shape[1:]),
    }
    digest = hashlib.sha256(
        json.dumps(context, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).digest()
    return int.from_bytes(digest[:8], "little"), context
