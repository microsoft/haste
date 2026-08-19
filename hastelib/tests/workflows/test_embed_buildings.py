# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for the building-embedding workflow's pure (torch-free) helpers.

The embedding model itself needs torch/torchgeo + a GPU-ish runtime, which are
only present in the training docker image — not in the unit-test env. So we
stub ``torch``/``torchgeo`` in ``sys.modules`` just enough to import the module
(the model classes are defined at import time) and then exercise the parts that
matter for correctness without ever running a model:

- ``pad_to_multiple`` / ``column_names`` — trivial but load-bearing.
- ``compute_crop_windows`` — keys crops by the building's NATIVE row index and
  drops buildings that don't overlap the raster.
- ``rasterize_building_in_token_grid`` — produces a token-grid boolean mask.
- ``assemble_output`` — THE row-order invariant: one output row per input
  footprint, native order, ``id = 0..N-1``, Overture id preserved as
  ``overture_id``, NaN-feature rows kept (never dropped/reordered).
"""

import hashlib
import sys
import types
import unittest
from types import SimpleNamespace

import pytest

# ── Stub torch / torchgeo so the module imports without the real deps ──────
for _name in ("torch", "torch.nn", "torch.nn.functional"):
    if _name not in sys.modules:
        sys.modules[_name] = types.ModuleType(_name)
# torch.Tensor / torch.no_grad used at class-definition time
sys.modules["torch"].Tensor = type("Tensor", (), {})
sys.modules["torch"].no_grad = lambda: (lambda fn: fn)
sys.modules["torch"].nn = sys.modules["torch.nn"]
sys.modules["torch.nn"].Module = type("Module", (), {})
sys.modules["torch.nn"].functional = sys.modules["torch.nn.functional"]
# torch.hub.{set_dir,load} are referenced at class-definition time inside
# _DinoV2PatchTokensWrapper; stub them out so they don't get called here.
sys.modules["torch.hub"] = types.ModuleType("torch.hub")
sys.modules["torch.hub"].set_dir = lambda *_a, **_kw: None
sys.modules["torch.hub"].load = lambda *_a, **_kw: None
sys.modules["torch"].hub = sys.modules["torch.hub"]
for _pkg in ("torchgeo", "torchgeo.models", "torchgeo.datasets"):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = types.ModuleType(_pkg)
sys.modules["torchgeo.models"].RCF = type("RCF", (), {})
sys.modules["torchgeo.datasets"].NonGeoDataset = type("NonGeoDataset", (), {})

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from hastegeo.workflows import embed_buildings as eb  # noqa: E402
from shapely.geometry import box  # noqa: E402


@pytest.fixture(autouse=True)
def fake_dinov3_snapshot_manifest(mocker):
    """Use tiny deterministic files instead of allocating the real snapshot."""
    contents = {
        "config.json": b"test",
        "model.safetensors": b"test",
    }
    manifest = {
        filename: {
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        }
        for filename, content in contents.items()
    }
    mocker.patch.object(eb, "DINOV3_SAT_SNAPSHOT_MANIFEST", manifest)


class TestPureHelpers(unittest.TestCase):
    def test_pad_to_multiple(self):
        self.assertEqual(eb.pad_to_multiple(1, 16), 16)
        self.assertEqual(eb.pad_to_multiple(16, 16), 16)
        self.assertEqual(eb.pad_to_multiple(17, 16), 32)

    def test_column_names(self):
        self.assertEqual(eb.column_names(3), ["f_0", "f_1", "f_2"])
        self.assertEqual(len(eb.column_names(1024)), 1024)


class TestComputeCropWindows(unittest.TestCase):
    def setUp(self):
        # 100x100 raster, 1 unit/px, origin (0, 100), y decreasing.
        self.transform = rasterio.transform.from_bounds(
            0, 0, 100, 100, 100, 100
        )
        self.h = self.w = 100

    def test_keeps_native_index_and_drops_outside(self):
        # idx 0: inside; idx 1: fully outside (to the right); idx 2: inside.
        geoms = [
            box(10, 10, 20, 20),
            box(200, 200, 210, 210),
            box(40, 40, 50, 50),
        ]
        gdf = gpd.GeoDataFrame(geometry=geoms)
        crops = eb.compute_crop_windows(
            gdf, self.transform, self.h, self.w, context_px=2, resize_factor=4
        )
        kept = {c["idx"] for c in crops}
        # Building 1 is outside the raster -> dropped; 0 and 2 kept by index.
        self.assertEqual(kept, {0, 2})
        for c in crops:
            self.assertGreater(c["padded_width"], 0)
            self.assertGreater(c["padded_height"], 0)
            self.assertEqual(c["padded_width"] % (16 // 4), 0)

    def test_large_crop_is_capped(self):
        # A building covering most of the raster must be capped to max_crop_px
        # so its upscaled crop can't exhaust GPU/CPU memory.
        gdf = gpd.GeoDataFrame(geometry=[box(5, 5, 95, 95)])
        crops = eb.compute_crop_windows(
            gdf,
            self.transform,
            self.h,
            self.w,
            context_px=2,
            resize_factor=4,
            max_crop_px=32,
        )
        self.assertEqual(len(crops), 1)
        self.assertLessEqual(crops[0]["width"], 32)
        self.assertLessEqual(crops[0]["height"], 32)

    def test_dinov2_patch_size_14_grain(self):
        # DINOv2 uses 14-pixel patches in MODEL space. With resize_factor=1
        # that means the SOURCE-pixel padding grain is also 14, so every
        # padded crop dimension must be a multiple of 14.
        gdf = gpd.GeoDataFrame(geometry=[box(10, 10, 20, 20)])
        crops = eb.compute_crop_windows(
            gdf,
            self.transform,
            self.h,
            self.w,
            context_px=2,
            resize_factor=1,
            patch_size=14,
        )
        self.assertEqual(len(crops), 1)
        self.assertEqual(crops[0]["padded_width"] % 14, 0)
        self.assertEqual(crops[0]["padded_height"] % 14, 0)


class TestRasterizeTokenGrid(unittest.TestCase):
    def test_mask_shape_and_nonempty(self):
        transform = rasterio.transform.from_bounds(0, 0, 160, 160, 160, 160)
        geom = box(0, 0, 160, 160)
        mask = eb.rasterize_building_in_token_grid(
            geom, transform, token_h=10, token_w=10, resize_factor=1
        )
        self.assertEqual(mask.shape, (10, 10))
        self.assertTrue(mask.any())

    def test_mask_respects_patch_size_14(self):
        # With patch_size=14 and resize_factor=1 the effective stride is 14
        # source px / token, so a 140x140 source crop produces a 10x10 grid.
        transform = rasterio.transform.from_bounds(0, 0, 140, 140, 140, 140)
        geom = box(0, 0, 140, 140)
        mask = eb.rasterize_building_in_token_grid(
            geom,
            transform,
            token_h=10,
            token_w=10,
            resize_factor=1,
            patch_size=14,
        )
        self.assertEqual(mask.shape, (10, 10))
        self.assertTrue(mask.all())


class TestAssembleOutputRowOrder(unittest.TestCase):
    """The critical invariant the Validation/Assessment reports depend on."""

    def test_row_order_preserved_with_nan_rows(self):
        geoms = [box(0, 0, 1, 1), box(2, 2, 3, 3), box(4, 4, 5, 5)]
        footprints = gpd.GeoDataFrame(
            {"id": ["ov_A", "ov_B", "ov_C"], "geometry": geoms},
            crs="EPSG:4326",
        )
        col_names = eb.column_names(2)
        feature_matrix = np.array(
            [[1.0, 2.0], [np.nan, np.nan], [5.0, 6.0]], dtype=np.float32
        )
        pixel_counts = np.array([3, 0, 7], dtype=np.int32)

        out = eb.assemble_output(
            footprints, feature_matrix, pixel_counts, col_names
        )

        # Exactly one row per input, native order, integer row-index id.
        self.assertEqual(len(out), 3)
        self.assertEqual(list(out["id"]), [0, 1, 2])
        # Overture id preserved (renamed), aligned to the same rows.
        self.assertEqual(list(out["overture_id"]), ["ov_A", "ov_B", "ov_C"])
        # The zero-token building keeps its slot with NaN features.
        self.assertTrue(np.isnan(out.loc[1, "f_0"]))
        self.assertEqual(out.loc[0, "f_0"], 1.0)
        self.assertEqual(out.loc[2, "f_1"], 6.0)
        self.assertEqual(list(out["emb_px_count"]), [3, 0, 7])
        self.assertEqual(out.crs.to_epsg(), 4326)


class TestFeaturesSidecar(unittest.TestCase):
    """The binary sidecar the labeler fetches once at session start."""

    def test_roundtrip(self):
        import struct
        import tempfile

        # Three buildings × two features; row-major. Row index is the id.
        rows = [
            [1.0, 2.0],
            [float("nan"), float("nan")],  # invalid slot
            [5.0, 6.0],
        ]
        gdf = gpd.GeoDataFrame(
            {
                "id": [0, 1, 2],
                "overture_id": ["ov_A", "ov_B", "ov_C"],
                "f_0": [r[0] for r in rows],
                "f_1": [r[1] for r in rows],
                "geometry": [box(0, 0, 1, 1) for _ in rows],
            },
            crs="EPSG:4326",
        )
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            out_path = tmp.name
        n, d = eb.write_features_sidecar(gdf, out_path)
        self.assertEqual((n, d), (3, 2))

        with open(out_path, "rb") as f:
            raw = f.read()

        # Header: magic + version + n + d (16 bytes)
        self.assertEqual(raw[0:4], eb.SIDECAR_MAGIC)
        ver, count, dim = struct.unpack("<III", raw[4:16])
        self.assertEqual(ver, eb.SIDECAR_VERSION)
        self.assertEqual(count, 3)
        self.assertEqual(dim, 2)
        self.assertEqual(len(raw), 16 + count * dim * 4)

        # Row-major f32 lookup by id.
        floats = np.frombuffer(raw[16:], dtype="<f4").reshape(count, dim)
        np.testing.assert_array_equal(floats[0], np.array([1.0, 2.0]))
        np.testing.assert_array_equal(floats[2], np.array([5.0, 6.0]))
        # The invalid row's NaN sentinel survives the round-trip.
        self.assertTrue(np.isnan(floats[1, 0]))
        self.assertTrue(np.isnan(floats[1, 1]))

    def test_rejects_dataframe_with_no_feature_columns(self):
        gdf = gpd.GeoDataFrame(
            {"id": [0], "geometry": [box(0, 0, 1, 1)]}, crs="EPSG:4326"
        )
        with self.assertRaises(ValueError):
            eb.write_features_sidecar(gdf, "/tmp/should_not_exist.bin")

    def test_feature_columns_sorted_numerically_not_lexically(self):
        # f_2 must come before f_10 in the sidecar layout (numeric order),
        # not after (lexical order). The labeler hard-codes this order.
        import tempfile

        gdf = gpd.GeoDataFrame(
            {
                "id": [0],
                "f_10": [10.0],
                "f_2": [2.0],
                "f_1": [1.0],
                "geometry": [box(0, 0, 1, 1)],
            },
            crs="EPSG:4326",
        )
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            out_path = tmp.name
        n, d = eb.write_features_sidecar(gdf, out_path)
        self.assertEqual((n, d), (1, 3))
        with open(out_path, "rb") as f:
            raw = f.read()
        floats = np.frombuffer(raw[16:], dtype="<f4")
        # Expect [f_1, f_2, f_10] in that order.
        np.testing.assert_array_equal(floats, np.array([1.0, 2.0, 10.0]))


def _stage_fake_dinov3_snapshot(tmp_path):
    model_path = tmp_path / "dinov3_sat"
    model_path.mkdir()
    for filename in eb._DinoV3SatPatchTokensWrapper.REQUIRED_FILES:
        (model_path / filename).write_bytes(b"test")
    return model_path


def _mock_transformers_import(mocker, model):
    import builtins

    auto_model = mocker.Mock()
    auto_model.from_pretrained.return_value = model
    transformers = SimpleNamespace(AutoModel=auto_model)
    real_import = builtins.__import__

    def import_module(name, *args, **kwargs):
        if name == "transformers":
            return transformers
        return real_import(name, *args, **kwargs)

    mocker.patch("builtins.__import__", side_effect=import_module)
    return auto_model


def _valid_dinov3_model(mocker):
    model = mocker.Mock()
    model.eval.return_value = model
    model.config = SimpleNamespace(
        model_type="dinov3_vit",
        patch_size=16,
        hidden_size=1024,
        num_register_tokens=4,
    )
    return model


def test_dinov3_sat_loads_snapshot_local_only(tmp_path, mocker):
    model_path = _stage_fake_dinov3_snapshot(tmp_path)
    model = _valid_dinov3_model(mocker)
    auto_model = _mock_transformers_import(mocker, model)

    wrapper = eb._DinoV3SatPatchTokensWrapper(str(model_path))

    assert wrapper.backbone is model
    auto_model.from_pretrained.assert_called_once_with(
        str(model_path),
        local_files_only=True,
        trust_remote_code=False,
        use_safetensors=True,
    )


def test_dinov3_sat_forward_strips_cls_and_register_tokens(tmp_path, mocker):
    model_path = _stage_fake_dinov3_snapshot(tmp_path)
    model = _valid_dinov3_model(mocker)
    hidden_state = np.arange(2 * 9 * 1024).reshape(2, 9, 1024)
    model.return_value = SimpleNamespace(last_hidden_state=hidden_state)
    _mock_transformers_import(mocker, model)
    wrapper = eb._DinoV3SatPatchTokensWrapper(str(model_path))
    input_tensor = mocker.Mock()
    input_tensor.dim.return_value = 4
    input_tensor.size.return_value = 3
    input_tensor.shape = (2, 3, 32, 32)

    result = wrapper.forward(input_tensor)

    assert result.shape == (2, 4, 1024)
    np.testing.assert_array_equal(result, hidden_state[:, 5:, :])
    model.assert_called_once_with(pixel_values=input_tensor)


@pytest.mark.parametrize(
    ("shape", "rank", "channels", "message"),
    [
        ((3, 32), 2, 3, "shape"),
        ((1, 1, 32, 32), 4, 1, "shape"),
        ((1, 3, 30, 32), 4, 3, "multiples of 16"),
        ((1, 3, 32, 30), 4, 3, "multiples of 16"),
    ],
)
def test_dinov3_sat_rejects_invalid_input_shape(
    tmp_path, mocker, shape, rank, channels, message
):
    model_path = _stage_fake_dinov3_snapshot(tmp_path)
    model = _valid_dinov3_model(mocker)
    _mock_transformers_import(mocker, model)
    wrapper = eb._DinoV3SatPatchTokensWrapper(str(model_path))
    input_tensor = mocker.Mock()
    input_tensor.dim.return_value = rank
    input_tensor.size.return_value = channels
    input_tensor.shape = shape

    with pytest.raises(ValueError, match=message):
        wrapper.forward(input_tensor)

    model.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model_type", "vit", "model_type"),
        ("patch_size", 14, "patch_size"),
        ("hidden_size", 768, "hidden_size"),
        ("num_register_tokens", -1, "num_register_tokens"),
        ("num_register_tokens", None, "num_register_tokens"),
    ],
)
def test_dinov3_sat_rejects_invalid_metadata(
    tmp_path, mocker, field, value, message
):
    model_path = _stage_fake_dinov3_snapshot(tmp_path)
    model = _valid_dinov3_model(mocker)
    setattr(model.config, field, value)
    _mock_transformers_import(mocker, model)

    with pytest.raises(ValueError, match=message):
        eb._DinoV3SatPatchTokensWrapper(str(model_path))


def test_dinov3_sat_rejects_missing_path():
    with pytest.raises(ValueError, match="model_path"):
        eb._DinoV3SatPatchTokensWrapper(None)


def test_dinov3_sat_rejects_missing_snapshot_file(tmp_path):
    model_path = tmp_path / "dinov3_sat"
    model_path.mkdir()
    (model_path / "config.json").write_text("{}")

    with pytest.raises(FileNotFoundError, match="model.safetensors"):
        eb._DinoV3SatPatchTokensWrapper(str(model_path))


def test_dinov3_sat_rejects_snapshot_size_mismatch(tmp_path):
    model_path = _stage_fake_dinov3_snapshot(tmp_path)
    (model_path / "model.safetensors").write_bytes(b"truncated")

    with pytest.raises(ValueError, match="size mismatch"):
        eb._DinoV3SatPatchTokensWrapper(str(model_path))


def test_dinov3_sat_rejects_snapshot_hash_mismatch(tmp_path):
    model_path = _stage_fake_dinov3_snapshot(tmp_path)
    (model_path / "config.json").write_bytes(b"evil")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        eb._DinoV3SatPatchTokensWrapper(str(model_path))


@pytest.mark.parametrize(
    "filename", ["weights.bin", "model.pt", "x.pth", "x.py"]
)
def test_dinov3_sat_rejects_unsafe_snapshot_files(tmp_path, filename):
    model_path = _stage_fake_dinov3_snapshot(tmp_path)
    (model_path / filename).write_bytes(b"unsafe")

    with pytest.raises(ValueError, match="unsafe file"):
        eb._DinoV3SatPatchTokensWrapper(str(model_path))


def test_dinov3_sat_rejects_unapproved_snapshot_file(tmp_path):
    model_path = _stage_fake_dinov3_snapshot(tmp_path)
    (model_path / "notes.txt").write_text("unexpected")

    with pytest.raises(ValueError, match="unexpected file"):
        eb._DinoV3SatPatchTokensWrapper(str(model_path))


def test_dinov3_sat_rejects_empty_snapshot_directory(tmp_path):
    model_path = _stage_fake_dinov3_snapshot(tmp_path)
    (model_path / "empty").mkdir()

    with pytest.raises(ValueError, match="must not contain directories"):
        eb._DinoV3SatPatchTokensWrapper(str(model_path))


def test_dinov3_sat_rejects_snapshot_symlink(tmp_path):
    model_path = _stage_fake_dinov3_snapshot(tmp_path)
    (model_path / "linked-config.json").symlink_to(model_path / "config.json")

    with pytest.raises(ValueError, match="symlinks"):
        eb._DinoV3SatPatchTokensWrapper(str(model_path))


def test_dinov3_sat_rejects_symlinked_snapshot_directory(tmp_path):
    model_path = _stage_fake_dinov3_snapshot(tmp_path)
    linked_path = tmp_path / "linked-model"
    linked_path.symlink_to(model_path, target_is_directory=True)

    with pytest.raises(ValueError, match="must not be a symlink"):
        eb._DinoV3SatPatchTokensWrapper(str(linked_path))


def test_dinov3_sat_factory_reports_model_contract(mocker):
    backbone = mocker.Mock()
    wrapper = mocker.patch.object(
        eb, "_DinoV3SatPatchTokensWrapper", return_value=backbone
    )
    wrapper.PATCH_SIZE = 16
    wrapper.FEATURE_DIM = 1024

    class FakeTensor:
        def __init__(self, values):
            self.values = values

        def view(self, *_shape):
            return self

    mocker.patch.object(
        eb.torch,
        "tensor",
        side_effect=lambda values: FakeTensor(values),
        create=True,
    )

    handle = eb.build_embedding_model(
        "dinov3_sat", model_path="inputs/models/dinov3_sat"
    )

    wrapper.assert_called_once_with("inputs/models/dinov3_sat")
    assert handle["model"] is backbone
    assert handle["patch_size"] == 16
    assert handle["feat_dim"] == 1024
    assert handle["img_mean"].values == [0.485, 0.456, 0.406]
    assert handle["img_std"].values == [0.229, 0.224, 0.225]


if __name__ == "__main__":
    unittest.main()
