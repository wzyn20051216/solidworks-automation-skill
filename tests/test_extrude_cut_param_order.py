"""@brief Verify FeatureCut4 parameter order in extrude_cut."""

import pytest


def test_extrude_cut_sd_flip_dir_flags(cut_model):
    """@brief Sd=True always; flip->Flip(arg1); direction->Dir(arg2)."""
    # Test flip=True, direction=True
    from scripts import sw_part
    sw_part.extrude_cut(cut_model, "Sketch1", 0.01, direction=True, flip=True)
    args = cut_model.FeatureManager.cut_calls[0]
    assert args[0] is True  # Sd
    assert args[1] is True  # Flip
    assert args[2] is True  # Dir

    cut_model.FeatureManager.cut_calls.clear()

    # Test flip=False, direction=False — Sd must stay True (fix validation)
    sw_part.extrude_cut(cut_model, "Sketch1", 0.01, direction=False, flip=False)
    args = cut_model.FeatureManager.cut_calls[0]
    assert args[0] is True  # Sd stays True even when direction=False
    assert args[1] is False  # Flip
    assert args[2] is False  # Dir


def test_extrude_cut_end_condition_depth_zero(cut_model):
    """@brief depth=0 must set end_condition (arg3) to 1 (Through All)."""
    from scripts import sw_part
    sw_part.extrude_cut(cut_model, "Sketch1", 0, direction=True)
    args = cut_model.FeatureManager.cut_calls[0]
    assert args[3] == 1  # end_condition = swEndCondThroughAll


def test_extrude_cut_assembly_scope_flags(cut_model):
    """@brief Assembly-scope flags (args 20-21) must be False for part docs."""
    from scripts import sw_part
    sw_part.extrude_cut(cut_model, "Sketch1", 0.01, direction=True)
    args = cut_model.FeatureManager.cut_calls[0]
    assert args[19] is True   # UseAutoSelect (NOT Merge)
    assert args[20] is False  # AssemblyFeatureScope
    assert args[21] is False  # AutoSelectComponents
